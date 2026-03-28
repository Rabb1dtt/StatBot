import asyncio
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, List, Dict

import cyrtranslit
from rapidfuzz import fuzz, process

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

import config
from database import PlayerDB


@dataclass
class ResolvedPlayer:
    understat_id: int
    name: str
    team: str
    league: str
    position: str


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _normalize(text: str) -> str:
    return _strip_accents(text).lower().strip()


def _transliterate(text: str) -> str:
    """Cyrillic to Latin."""
    return cyrtranslit.to_latin(text, "ru")


class NameResolver:
    def __init__(self, db: PlayerDB) -> None:
        self.db = db
        self._players: List[Dict] = []
        self._search_index: Dict[str, Dict] = {}  # name_search -> player dict
        if OpenAI and config.OPENROUTER_API_KEY:
            self._llm = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.OPENROUTER_API_KEY,
            )
        else:
            self._llm = None
        self.model_translate = config.MODEL_TRANSLATE
        self.model_orchestrator = config.MODEL_ORCHESTRATOR
        self.model_search = config.MODEL_SEARCH

    def rebuild_index(self) -> None:
        """Reload players from DB into memory for fast search."""
        self._players = self.db.get_all_players_for_search()
        self._search_index = {}
        for p in self._players:
            key = p["name_search"]
            # Keep the one with more data (higher understat_id usually = more recent)
            if key not in self._search_index:
                self._search_index[key] = p

    def _fuzzy_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Local fuzzy search across all players."""
        if not self._search_index:
            return []

        # Try multiple query variants
        variants = set()
        variants.add(_normalize(query))
        variants.add(_normalize(_transliterate(query)))
        # Surname only
        parts = query.strip().split()
        if len(parts) > 1:
            variants.add(_normalize(parts[-1]))
            variants.add(_normalize(_transliterate(parts[-1])))

        choices = list(self._search_index.keys())
        best_results: Dict[int, tuple] = {}  # understat_id -> (score, player)

        for variant in variants:
            matches = process.extract(
                variant, choices, scorer=fuzz.WRatio, limit=limit
            )
            for name_key, score, _ in matches:
                player = self._search_index[name_key]
                uid = player["understat_id"]
                if uid not in best_results or score > best_results[uid][0]:
                    best_results[uid] = (score, player)

        # Sort by score descending, return (score, player) tuples
        sorted_results = sorted(best_results.values(), key=lambda x: x[0], reverse=True)
        return sorted_results[:limit]

    def _pick_best(
        self, results: List[tuple], team_hint: Optional[str] = None,
    ) -> Optional[tuple]:
        """Pick the best (score, player) result, boosting team_hint matches."""
        if not results:
            return None
        if not team_hint or len(results) == 1:
            return results[0]

        # Transliterate hint for matching
        hint_lower = _normalize(team_hint)
        hint_latin = _normalize(_transliterate(team_hint))

        for score, player in results:
            team = _normalize(player.get("team", ""))
            if hint_lower in team or hint_latin in team or team in hint_lower or team in hint_latin:
                return (score, player)
        # No team match — return first (best fuzzy)
        return results[0]

    def _to_resolved(self, score: float, player: Dict) -> ResolvedPlayer:
        return ResolvedPlayer(
            understat_id=player["understat_id"],
            name=player["name"],
            team=player.get("team", ""),
            league=player.get("league", ""),
            position=player.get("position", ""),
        )

    async def resolve(self, query: str, team_hint: Optional[str] = None) -> Optional[ResolvedPlayer]:
        """Resolve a player name query to a ResolvedPlayer.
        Always uses LLM first for transliteration, then fuzzy search.
        """
        MIN_SCORE = 55
        best = None

        # 1) LLM transliteration first — handles Cyrillic, nicknames, unusual names
        if self._llm:
            guess = await self._guess_latin_name(query)
            if guess:
                llm_results = self._fuzzy_search(guess, limit=10)
                best = self._pick_best(llm_results, team_hint)

        # 2) Also try direct fuzzy on original query — pick better of the two
        direct_results = self._fuzzy_search(query, limit=10)
        direct_best = self._pick_best(direct_results, team_hint)
        if direct_best:
            if not best or direct_best[0] > best[0]:
                best = direct_best

        if best and best[0] >= MIN_SCORE:
            return self._to_resolved(*best)
        return None

    def _try_match_query(self, query: str) -> Optional[dict]:
        """Detect match analysis queries with optional filters (all regex, no LLM needed)."""
        q = query.strip()
        ql = q.lower()

        # Match indicators: "против" in non-comparison context, "последний матч", "матч", "как сыграл"
        is_match_query = False

        # "как сыграл/играл X" prefix → definitely a match query
        if re.match(r'^как\s+(?:сыграл|играл)', ql):
            is_match_query = True

        # "X последний матч" / "X вчера"
        if re.search(r'(?:последний матч|last match|вчера|yesterday|сегодня|today)$', ql):
            is_match_query = True

        # Contains filter words that only make sense for match queries
        match_filters = ['в лиге', 'в лч', 'в кубке', 'в ла лиге', 'в серии',
                         'в бундеслиге', 'в лиге 1', 'в рпл', 'в апл',
                         'в лиге чемпионов', 'в лиге европы', 'champions league',
                         'premier league', 'за карьеру', 'за все время', 'all time',
                         'последние', 'первый круг', 'второй круг',
                         'в fa cup', 'в кубке англии', 'в кубке испании']
        for f in match_filters:
            if f in ql:
                is_match_query = True
                break

        # "X против Y" where Y looks like a team (not a player comparison)
        # If "сравни" is NOT present and "против" IS present → likely match
        if 'против' in ql and 'сравни' not in ql and 'сравнить' not in ql:
            # But only if no other comparison markers (vs between two player-like names with "и")
            if not re.search(r'\s+и\s+.+\s+против\s+', ql):
                is_match_query = True

        if not is_match_query:
            return None

        # === Extract parameters ===
        # Remove prefixes
        cleaned = re.sub(r'^(?:как\s+(?:сыграл|играл)\s+)', '', q, flags=re.IGNORECASE).strip()

        # Extract count: "последние N матч(ей/а)"
        count = None
        count_match = re.search(r'последни[ех]\s+(\d+)\s+(?:матч|игр)', cleaned, flags=re.IGNORECASE)
        if count_match:
            count = int(count_match.group(1))
            cleaned = cleaned[:count_match.start()] + cleaned[count_match.end():]

        # Extract all_time
        all_time = False
        if re.search(r'за\s+(?:карьеру|все\s+время|всю\s+карьеру)|all\s+time', cleaned, flags=re.IGNORECASE):
            all_time = True
            cleaned = re.sub(r'за\s+(?:карьеру|все\s+время|всю\s+карьеру)|all\s+time', '', cleaned, flags=re.IGNORECASE)

        # Extract tournament filter
        tournament = None
        tourney_patterns = {
            r'в\s+(?:лч|лиге\s+чемпионов|champions\s+league)': 'Champions League',
            r'в\s+(?:ле|лиге\s+европы|europa\s+league)': 'Europa League',
            r'в\s+(?:апл|премьер[\s-]лиге|premier\s+league)': 'Premier League',
            r'в\s+(?:ла\s+лиге|la\s+liga)': 'LaLiga',
            r'в\s+(?:серии\s+а|serie\s+a)': 'Serie A',
            r'в\s+(?:бундеслиге|bundesliga)': 'Bundesliga',
            r'в\s+(?:лиге\s+1|ligue\s+1)': 'Ligue 1',
            r'в\s+(?:рпл)': 'Premier League',  # Russian PL
            r'в\s+(?:финале\s+)?(?:кубке?\s+англии|fa\s+cup)': 'FA Cup',
            r'в\s+(?:финале\s+)?(?:кубке?\s+лиги|кубке?\s+карабао|carabao|efl\s+cup)': 'EFL Cup',
            r'в\s+(?:финале\s+)?(?:кубке?\s+испании|copa\s+del\s+rey)': 'Copa del Rey',
            r'в\s+(?:финале\s+)?(?:кубке?\s+германии|dfb\s+pokal)': 'DFB Pokal',
            r'в\s+(?:финале\s+)?(?:кубке?\s+италии|coppa\s+italia)': 'Coppa Italia',
            r'в\s+(?:финале\s+)?(?:кубке?\s+франции|coupe\s+de\s+france)': 'Coupe de France',
            r'в\s+(?:финале\s+)?кубк[еау]': 'EFL Cup',  # generic "в кубке" / "в финале кубка"
            r'в\s+лиге(?!\s+(?:чемпионов|европы))': 'league',  # generic "в лиге"
        }
        for pattern, name in tourney_patterns.items():
            if re.search(pattern, cleaned, flags=re.IGNORECASE):
                tournament = name
                cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
                break

        # Extract opponent: "против X"
        opponent = None
        vs_match = re.search(r'(?:против|vs\.?|versus)\s+(.+?)(?:\s*$)', cleaned, flags=re.IGNORECASE)
        if vs_match:
            opponent = vs_match.group(1).strip()
            cleaned = cleaned[:vs_match.start()]

        # Remove "последний матч" / "вчера"
        cleaned = re.sub(r'\s*(?:последний\s+матч|last\s+match|вчера|yesterday|сегодня|today)\s*', ' ', cleaned, flags=re.IGNORECASE)

        # What's left is the player name
        player_name = cleaned.strip().rstrip(',.- ')
        if not player_name:
            return None

        return {
            "type": "match",
            "names": [self._clean_name(player_name)],
            "team_hints": [self._extract_team_hint(player_name)],
            "opponent": opponent,
            "tournament": tournament,
            "count": count,
            "all_time": all_time,
        }

    def _try_fast_split(self, query: str) -> Optional[dict]:
        """Fast regex-based detection of comparison queries without LLM."""
        q = query.strip()

        # Remove "сравни"/"сравнить"/"compare" prefix
        q_clean = re.sub(r'^(сравни(?:ть)?|compare)\s+', '', q, flags=re.IGNORECASE).strip()
        if q_clean != q:
            # Had a comparison prefix — split the rest
            raw_parts = self._split_raw(q_clean)
            if len(raw_parts) >= 2:
                return self._build_compare(raw_parts[:5])

        # Check for "vs", "против", comma separators
        separators = r'\s+(?:vs\.?|versus|против)\s+|\s*,\s*'
        parts = re.split(separators, q, flags=re.IGNORECASE)
        if len(parts) >= 2:
            raw_parts = [p.strip() for p in parts if p.strip()]
            if len(raw_parts) >= 2:
                return self._build_compare(raw_parts[:5])

        # Try " и " split — but only if result has 2+ non-empty parts
        parts = re.split(r'\s+и\s+', q, flags=re.IGNORECASE)
        if len(parts) >= 2:
            raw_parts = [p.strip() for p in parts if p.strip()]
            if len(raw_parts) >= 2 and all(len(p.split()) <= 5 for p in raw_parts):
                return self._build_compare(raw_parts[:5])

        return None

    def _split_raw(self, text: str) -> list[str]:
        """Split text into raw parts (keeping parentheses)."""
        parts = re.split(r'\s+(?:vs\.?|versus|против|и)\s+|\s*,\s*', text, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _build_compare(self, raw_parts: list[str]) -> dict:
        """Build compare result with names and team hints."""
        names = [self._clean_name(p) for p in raw_parts]
        hints = [self._extract_team_hint(p) for p in raw_parts]
        return {"type": "compare", "names": names, "team_hints": hints}

    def _clean_name(self, raw: str) -> str:
        """Remove team hints in parentheses: 'Винисиус (Реал Мадрид)' → 'Винисиус'."""
        return re.sub(r'\s*\([^)]*\)\s*', ' ', raw).strip()

    def _extract_team_hint(self, raw: str) -> Optional[str]:
        """Extract team hint from parentheses: 'Винисиус (Реал Мадрид)' → 'Реал Мадрид'."""
        m = re.search(r'\(([^)]+)\)', raw)
        return m.group(1).strip() if m else None

    async def parse_query(self, query: str) -> dict:
        """
        Sonnet orchestrator parses ALL queries. No regex fallback.
        Returns: {"type": "single"|"compare"|"match", "names": [...], ...}
        """
        if not self._llm:
            return {"type": "single", "names": [query], "team_hints": [None]}

        prompt = (
            "You are a football stats bot query router. Parse the user's query and extract structured parameters.\n\n"
            "QUERY TYPES:\n"
            "1) single — user wants season stats for ONE player. Example: 'Холанд', 'покажи Салаха'\n"
            "2) compare — user wants to COMPARE 2-5 players. Example: 'сравни Салаха и Мбаппе', 'Холанд vs Ямал vs Палмер'\n"
            "3) match — user wants to see how a player performed in SPECIFIC MATCH(ES). "
            "Example: 'Орайли против Арсенала в финале кубка', 'Фоден последний матч', 'как Ямал сыграл против Реала в ЛЧ'\n"
            "4) coach — user wants to evaluate a COACH's work this season. "
            "Extract the coach's name, appointment date (COACH_SINCE), and departure date (COACH_UNTIL) if they were fired/left. "
            "Use your knowledge - e.g. Arteta at Arsenal since Dec 2019, Slot at Liverpool since Jun 2024. "
            "If the coach is STILL at the club, COACH_UNTIL = CURRENT. "
            "If they were fired/left, give the date. If unsure, use UNKNOWN.\n"
            "Example: 'тренер Ливерпуля', 'оценка Гвардиолы', 'как работает Анчелотти', 'coach Arteta'\n"
            "5) team — user wants TEAM season analysis. "
            "Example: 'сезон Ливерпуля', 'как играет Арсенал', 'оценка Реала', 'команда Барселона'\n"
            "6) compare_coaches — user wants to COMPARE 2+ coaches/teams. "
            "Example: 'сравни тренеров Ливерпуля и Арсенала', 'Гвардиола vs Артета', 'Арсенал vs Ливерпуль сезон'\n\n"

            "RULES FOR PLAYER NAMES:\n"
            "- Extract the actual player name, removing qualifiers like 'последние 2 матча', 'в лиге' etc.\n"
            "- If name has team hint in parentheses like 'Винисиус (Реал)', put team in TEAM_HINT field.\n"
            "- Player names can be in any language. Transliterate to Latin for PLAYER fields.\n"
            "- For compare: extract ALL player names (up to 5).\n\n"

            "RULES FOR MATCH TYPE:\n"
            "- OPPONENT: the team they played against (in English). NONE if 'last match' / 'вчера'.\n"
            "- TOURNAMENT: which competition. Use standard English names:\n"
            "  Champions League, Europa League, Conference League,\n"
            "  Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, RPL,\n"
            "  FA Cup, EFL Cup, Copa del Rey, DFB Pokal, Coppa Italia, Coupe de France.\n"
            "  Use ALL if no specific tournament mentioned.\n"
            "- COUNT: how many matches (number). ALL if not specified.\n"
            "- ALL_TIME: yes if user asks about entire career / 'за карьеру' / 'all time'. Otherwise no.\n\n"

            "EXAMPLES:\n"
            "- 'Холанд' → TYPE: single, PLAYER1: Erling Haaland\n"
            "- 'сравни Салаха и Мбаппе' → TYPE: compare, PLAYER1: Mohamed Salah, PLAYER2: Kylian Mbappe\n"
            "- 'Винисиус (Реал) vs Доку (Сити)' → TYPE: compare, PLAYER1: Vinicius Junior, TEAM_HINT1: Real Madrid, PLAYER2: Jeremy Doku, TEAM_HINT2: Manchester City\n"
            "- 'Орайли против Арсенала в финале кубка' → TYPE: match, PLAYER1: Nico O'Reilly, OPPONENT: Arsenal, TOURNAMENT: EFL Cup, COUNT: ALL\n"
            "- 'Хусанов последние 2 матча против Реала в ЛЧ' → TYPE: match, PLAYER1: Abdukodir Khusanov, OPPONENT: Real Madrid, TOURNAMENT: Champions League, COUNT: 2\n"
            "- 'Фоден против МЮ за карьеру' → TYPE: match, PLAYER1: Phil Foden, OPPONENT: Manchester United, TOURNAMENT: ALL, COUNT: ALL, ALL_TIME: yes\n"
            "- 'Салах последний матч' → TYPE: match, PLAYER1: Mohamed Salah, OPPONENT: NONE, COUNT: 1\n"
            "- 'как Ямал сыграл против Реала' → TYPE: match, PLAYER1: Lamine Yamal, OPPONENT: Real Madrid, TOURNAMENT: ALL, COUNT: ALL\n"
            "- 'тренер Ливерпуля' → TYPE: coach, TEAM: Liverpool, LEAGUE: Premier League, COACH_NAME: Arne Slot, COACH_SINCE: 2024-06-01\n"
            "- 'оценка Гвардиолы' → TYPE: coach, TEAM: Manchester City, LEAGUE: Premier League, COACH_NAME: Pep Guardiola, COACH_SINCE: 2016-07-01\n"
            "- 'как работает Слот' → TYPE: coach, TEAM: Liverpool, LEAGUE: Premier League, COACH_NAME: Arne Slot, COACH_SINCE: 2024-06-01\n"
            "- 'сезон Арсенала' → TYPE: team, TEAM: Arsenal, LEAGUE: Premier League\n"
            "- 'как играет Барселона' → TYPE: team, TEAM: Barcelona, LEAGUE: LaLiga\n"
            "- 'Реал Мадрид сезон' → TYPE: team, TEAM: Real Madrid, LEAGUE: LaLiga\n"
            "- 'сравни тренеров Ливерпуля и Арсенала' → TYPE: compare_coaches, TEAM: Liverpool, LEAGUE: Premier League, TEAM2: Arsenal, LEAGUE2: Premier League\n"
            "- 'Гвардиола vs Артета' → TYPE: compare_coaches, TEAM: Manchester City, LEAGUE: Premier League, TEAM2: Arsenal, LEAGUE2: Premier League\n"
            "- 'Арсенал vs Ливерпуль сезон' → TYPE: compare_coaches, TEAM: Arsenal, LEAGUE: Premier League, TEAM2: Liverpool, LEAGUE2: Premier League\n\n"

            "Reply STRICTLY in this format (one field per line, no extra text):\n"
            "TYPE: single|compare|match|coach|team|compare_coaches\n"
            "PLAYER1: <name in Latin> (for single/compare/match)\n"
            "TEAM_HINT1: <team or NONE>\n"
            "PLAYER2: <name or skip>\n"
            "TEAM_HINT2: <team or NONE>\n"
            "(PLAYER3-5 + TEAM_HINT3-5 if needed)\n"
            "OPPONENT: <team in English or NONE> (for match)\n"
            "TOURNAMENT: <name or ALL> (for match)\n"
            "COUNT: <number or ALL> (for match)\n"
            "ALL_TIME: yes|no (for match)\n"
            "TEAM: <team name in English> (for coach/team/compare_coaches)\n"
            "LEAGUE: <league name> (for coach/team/compare_coaches)\n"
            "COACH_NAME: <coach full name> (for coach/compare_coaches)\n"
            "COACH_SINCE: <YYYY-MM-DD or UNKNOWN> (for coach/compare_coaches)\n"
            "COACH_UNTIL: <YYYY-MM-DD or CURRENT or UNKNOWN> (for coach/compare_coaches)\n"
            "TEAM2: <second team> (for compare_coaches)\n"
            "LEAGUE2: <second league> (for compare_coaches)\n"
            "COACH_NAME2: <second coach> (for compare_coaches)\n"
            "COACH_SINCE2: <YYYY-MM-DD or UNKNOWN> (for compare_coaches)\n"
            "COACH_UNTIL2: <YYYY-MM-DD or CURRENT or UNKNOWN> (for compare_coaches)\n\n"
            f"Query: {query}"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_orchestrator,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()

            text = await asyncio.to_thread(_call)
            qtype = "single"
            names = []
            team_hints = []
            opponent = None
            tournament = None
            count = None
            all_time = False
            team_name = None
            league_name = None

            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                key_val = line.split(":", 1)
                if len(key_val) != 2:
                    continue
                key = key_val[0].strip().upper()
                val = key_val[1].strip()

                if key == "TYPE":
                    v = val.lower()
                    if v in ("compare", "match", "single", "coach", "team", "compare_coaches"):
                        qtype = v
                elif re.match(r'^PLAYER\d+$', key):
                    if val and val.upper() != "NONE":
                        names.append(val)
                elif re.match(r'^TEAM_HINT\d+$', key):
                    hint = val if val.upper() != "NONE" else None
                    team_hints.append(hint)
                elif key == "OPPONENT":
                    if val.upper() != "NONE":
                        opponent = val
                elif key == "TOURNAMENT":
                    if val.upper() != "ALL":
                        tournament = val
                elif key == "COUNT":
                    if val.upper() != "ALL":
                        try:
                            count = int(val)
                        except ValueError:
                            pass
                elif key == "ALL_TIME":
                    all_time = val.lower() in ("yes", "true")
                elif key == "TEAM":
                    if val and val.upper() != "NONE":
                        team_name = val
                elif key == "LEAGUE":
                    if val and val.upper() != "NONE":
                        league_name = val
                elif key == "COACH_NAME":
                    if val and val.upper() not in ("NONE", "UNKNOWN"):
                        if "coach_name" not in locals():
                            coach_name = val
                elif key == "COACH_SINCE":
                    if val and val.upper() not in ("NONE", "UNKNOWN"):
                        if "coach_since" not in locals():
                            coach_since = val
                elif key == "COACH_UNTIL":
                    if val and val.upper() not in ("NONE", "UNKNOWN", "CURRENT"):
                        if "coach_until" not in locals():
                            coach_until = val
                elif key == "TEAM2":
                    if val and val.upper() != "NONE":
                        if "teams" not in locals():
                            teams = []
                        teams.append(val)
                elif key == "LEAGUE2":
                    if val and val.upper() != "NONE":
                        if "leagues" not in locals():
                            leagues = []
                        leagues.append(val)
                elif key == "COACH_NAME2":
                    if val and val.upper() not in ("NONE", "UNKNOWN"):
                        if "coach_names" not in locals():
                            coach_names = []
                        coach_names.append(val)
                elif key == "COACH_SINCE2":
                    if val and val.upper() not in ("NONE", "UNKNOWN"):
                        if "coach_sinces" not in locals():
                            coach_sinces = []
                        coach_sinces.append(val)

            # Compare coaches/teams
            if qtype == "compare_coaches" and team_name:
                team_list = [team_name] + (teams if "teams" in locals() else [])
                league_list = [league_name] + (leagues if "leagues" in locals() else [])
                cn = [coach_name] if "coach_name" in locals() else []
                cn += coach_names if "coach_names" in locals() else []
                cs = [coach_since] if "coach_since" in locals() else []
                cs += coach_sinces if "coach_sinces" in locals() else []
                return {
                    "type": "compare_coaches",
                    "names": team_list,
                    "team_hints": [None] * len(team_list),
                    "teams": team_list,
                    "leagues": league_list,
                    "coach_names": cn,
                    "coach_sinces": cs,
                }

            # Coach/team queries
            if qtype in ("coach", "team") and team_name:
                return {
                    "type": qtype,
                    "names": [team_name],
                    "team_hints": [None],
                    "team": team_name,
                    "league": league_name,
                    "coach_name": coach_name if "coach_name" in locals() else None,
                    "coach_since": coach_since if "coach_since" in locals() else None,
                    "coach_until": coach_until if "coach_until" in locals() else None,
                }

            if not names:
                return {"type": "single", "names": [query], "team_hints": [None]}

            # Pad team_hints to match names
            while len(team_hints) < len(names):
                team_hints.append(None)

            result = {
                "type": qtype,
                "names": names,
                "team_hints": team_hints,
            }
            if qtype == "match":
                result["opponent"] = opponent
                result["tournament"] = tournament
                result["count"] = count
                result["all_time"] = all_time
            return result
        except Exception:
            return {"type": "single", "names": [query], "team_hints": [None]}

    async def _guess_latin_name(self, query: str) -> Optional[str]:
        if not self._llm:
            return None
        prompt = (
            "You are a football player name resolver. "
            "The user gives a player name in ANY language/script/spelling/nickname. "
            "Your job: return the player's REAL NAME in Latin script as used in official databases.\n\n"
            "Examples:\n"
            "- 'Нико Орайли' → 'Nico O'Reilly'\n"
            "- 'Рюдигер' → 'Antonio Rudiger'\n"
            "- 'Мбаппе' → 'Kylian Mbappe'\n"
            "- 'Холанд' → 'Erling Haaland'\n"
            "- 'Анхель ди Мария' → 'Angel Di Maria'\n"
            "- 'Щесны' → 'Wojciech Szczesny'\n\n"
            "Reply with ONLY the full name in Latin script, nothing else.\n"
            f"Query: {query}"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_translate,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            return await asyncio.to_thread(_call)
        except Exception:
            return None

    async def _guess_coach_departure(self, coach_name: str, team_name: str, current_manager: str) -> Optional[str]:
        """Ask Sonnet when a coach left a club, given that a new manager is now in charge."""
        if not self._llm:
            return None
        prompt = (
            f"When did {coach_name} leave or get fired from {team_name} football club? "
            f"I know the current manager is {current_manager}. "
            f"Reply with ONLY the date in YYYY-MM-DD format. Nothing else."
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            result = await asyncio.to_thread(_call)
            # Extract date from response (may have extra text)
            import re as _re
            date_match = _re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', result or "")
            if date_match:
                d = date_match.group(1)
                if len(d) == 7:
                    d += "-28"
                return d[:10]
            return None
        except Exception:
            return None
