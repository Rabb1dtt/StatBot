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
        Parse user query: try regex first, then LLM (mimo) for complex/ambiguous queries.
        Returns: {"type": "single"|"compare"|"match"|"coach"|"team"|"compare_coaches", "names": [...], ...}
        """
        if not self._llm:
            return {"type": "single", "names": [query], "team_hints": [None]}

        prompt = (
            "# TASK\n"
            "Parse a football stats query. Extract the type and structured fields.\n\n"

            "# TYPES\n"
            "- single: stats for ONE player. Ex: 'Холанд', 'покажи Салаха'\n"
            "- compare: compare 2-5 players. Ex: 'сравни Салаха и Мбаппе'\n"
            "- match: player's performance in specific match(es). Ex: 'Фоден последний матч', 'Ямал против Реала в ЛЧ'\n"
            "- coach: evaluate a coach. Ex: 'тренер Ливерпуля', 'оценка Гвардиолы'\n"
            "- team: team season analysis. Ex: 'сезон Арсенала', 'как играет Барселона'\n"
            "- compare_coaches: compare 2+ coaches. Ex: 'Гвардиола vs Артета', 'Почеттино vs Мареска'\n\n"

            "# HOW TO DECIDE TYPE\n"
            "- Words 'сравни', 'сравнить', 'compare', 'vs' between names → compare or compare_coaches\n"
            "- Words 'тренер', 'coach', 'оцени тренера', coach surname without player context → coach\n"
            "- Words 'сезон команды', 'как играет [team]', 'оценка [team]' → team\n"
            "- Words 'против [team]', 'последний матч', 'как сыграл', 'вчера' → match\n"
            "- Just a player name or 'покажи [name]' → single\n\n"

            "# RULES\n"
            "- Transliterate ALL player/coach names to Latin script\n"
            "- Team names in English (e.g. Ливерпуль → Liverpool)\n"
            "- If name has team hint in parentheses like 'Винисиус (Реал)' → put team in TEAM_HINT\n"
            "- OPPONENT = team played against (English). NONE if not specified\n"
            "- TOURNAMENT = competition name in English (Champions League, Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, FA Cup, EFL Cup, Copa del Rey, etc). ALL if not specified\n"
            "- COUNT = number of matches. ALL if not specified\n"
            "- ALL_TIME = yes ONLY if user says 'за карьеру'/'за всё время'/'all time'/'за весь период'. Otherwise no\n"
            "- COACH_SINCE: appointment date as YYYY-MM-DD, or UNKNOWN\n"
            "- COACH_UNTIL: departure date, or CURRENT, or UNKNOWN\n"
            "- SEASON: if user specifies a season (e.g. '2022-2023', 'сезон 2021/22'), extract the START YEAR as 4-digit number. NONE if current season\n"
            "- TEAM_FILTER: if user specifies a specific club context (e.g. 'в Ман Сити', 'когда играл в Барселоне'), extract team name in English. NONE if not specified\n\n"

            "# EXAMPLES\n"
            "'Холанд' →\n"
            "TYPE: single\n"
            "PLAYER1: Erling Haaland\n\n"

            "'сравни Салаха и Мбаппе' →\n"
            "TYPE: compare\n"
            "PLAYER1: Mohamed Salah\n"
            "PLAYER2: Kylian Mbappe\n\n"

            "'Фоден против МЮ за карьеру' →\n"
            "TYPE: match\n"
            "PLAYER1: Phil Foden\n"
            "OPPONENT: Manchester United\n"
            "TOURNAMENT: ALL\n"
            "COUNT: ALL\n"
            "ALL_TIME: yes\n\n"

            "'тренер Ливерпуля' →\n"
            "TYPE: coach\n"
            "TEAM: Liverpool\n"
            "LEAGUE: Premier League\n"
            "COACH_NAME: Arne Slot\n"
            "COACH_SINCE: 2024-06-01\n\n"

            "'сезон Арсенала' →\n"
            "TYPE: team\n"
            "TEAM: Arsenal\n"
            "LEAGUE: Premier League\n\n"

            "'Гвардиола vs Артета' →\n"
            "TYPE: compare_coaches\n"
            "COACH_NAME: Pep Guardiola\n"
            "COACH_NAME2: Mikel Arteta\n\n"

            "'Почеттино vs Мареска в Челси' →\n"
            "TYPE: compare_coaches\n"
            "COACH_NAME: Mauricio Pochettino\n"
            "TEAM: Chelsea\n"
            "LEAGUE: Premier League\n"
            "COACH_NAME2: Enzo Maresca\n"
            "TEAM2: Chelsea\n"
            "LEAGUE2: Premier League\n\n"

            "'Де Брюйне сезон 2022-2023 в Ман Сити' →\n"
            "TYPE: single\n"
            "PLAYER1: Kevin De Bruyne\n"
            "TEAM_HINT1: Manchester City\n"
            "SEASON: 2022\n\n"

            "'сравни Салаха 2021/22 и Мбаппе 2021/22' →\n"
            "TYPE: compare\n"
            "PLAYER1: Mohamed Salah\n"
            "PLAYER2: Kylian Mbappe\n"
            "SEASON: 2021\n\n"

            "# OUTPUT FORMAT\n"
            "Reply with ONLY the fields, one per line. No extra text, no explanations.\n"
            "Only include fields that are relevant to the detected TYPE.\n\n"

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
            season_year = None
            team_filter = None

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
                elif key == "SEASON":
                    if val and val.upper() != "NONE":
                        # Extract 4-digit year
                        m = re.search(r'(\d{4})', val)
                        if m:
                            season_year = m.group(1)
                elif key == "TEAM_FILTER":
                    if val and val.upper() != "NONE":
                        team_filter = val
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

            # Compare coaches
            if qtype == "compare_coaches":
                cn = []
                ct = []  # coach teams
                cl = []  # coach leagues
                if "coach_name" in locals() and coach_name:
                    cn.append(coach_name)
                    ct.append(team_name or "")
                    cl.append(league_name or "")
                if "coach_names" in locals():
                    cn.extend(coach_names)
                # Build teams list: TEAM2 maps to second coach, etc.
                extra_teams = teams if "teams" in locals() else []
                extra_leagues = leagues if "leagues" in locals() else []
                for i in range(len(cn) - len(ct)):
                    ct.append(extra_teams[i] if i < len(extra_teams) else "")
                    cl.append(extra_leagues[i] if i < len(extra_leagues) else "")

                return {
                    "type": "compare_coaches",
                    "names": cn,
                    "team_hints": [None] * len(cn),
                    "coach_names": cn,
                    "teams": ct,
                    "leagues": cl,
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
                    "all_time": all_time,
                }

            if not names:
                return {"type": "single", "names": [query], "team_hints": [None]}

            # Pad team_hints to match names
            while len(team_hints) < len(names):
                team_hints.append(None)

            # Use team_filter as team_hint if no explicit hint
            if team_filter and team_hints and all(h is None for h in team_hints):
                team_hints[0] = team_filter

            result = {
                "type": qtype,
                "names": names,
                "team_hints": team_hints,
            }
            if season_year:
                result["season"] = season_year
            if team_filter:
                result["team_filter"] = team_filter
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

    async def search_coach_info(self, query: str) -> Optional[Dict]:
        """Use search model to get current coach info for a team.
        Returns: {coach_name, coach_since, coach_until, league} or None.
        """
        if not self._llm:
            return None
        prompt = (
            f"Who is the current head coach/manager of {query} football club? "
            f"When were they appointed? "
            f"Reply in this EXACT format (one field per line):\n"
            f"COACH_NAME: <full name>\n"
            f"TEAM: <team name in English>\n"
            f"LEAGUE: <league name: Premier League / LaLiga / Serie A / Bundesliga / Ligue 1 / RPL>\n"
            f"COACH_SINCE: <YYYY-MM-DD appointment date>\n"
            f"PREVIOUS_COACH: <name of previous coach or NONE>\n"
            f"PREVIOUS_COACH_LEFT: <YYYY-MM-DD when previous coach left or NONE>"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            # Clean Perplexity citation refs [1], [2], etc.
            text = re.sub(r'\[\d+\]', '', text)

            result = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip().upper().replace("*", "")
                val = val.strip().strip("*")
                if val.upper() in ("NONE", "UNKNOWN", "N/A"):
                    continue

                if key == "COACH_NAME":
                    result["coach_name"] = val
                elif key == "TEAM":
                    result["team"] = val
                elif key == "LEAGUE":
                    result["league"] = val
                elif key == "COACH_SINCE":
                    date_match = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', val)
                    if date_match:
                        d = date_match.group(1)
                        result["coach_since"] = d if len(d) == 10 else d + "-01"
                elif key == "PREVIOUS_COACH":
                    result["previous_coach"] = val
                elif key == "PREVIOUS_COACH_LEFT":
                    date_match = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', val)
                    if date_match:
                        d = date_match.group(1)
                        result["previous_coach_left"] = d if len(d) == 10 else d + "-01"

            return result if result.get("coach_name") else None
        except Exception:
            return None

    async def search_specific_coach(self, coach_name: str, team_name: str) -> Optional[Dict]:
        """Search for a SPECIFIC coach's tenure at a team (may be former coach)."""
        if not self._llm:
            return None
        prompt = (
            f"When was {coach_name} appointed as head coach of {team_name} football club? "
            f"Are they STILL the head coach of {team_name}, or were they fired/left? "
            f"If they left, when exactly?\n\n"
            f"Reply in this EXACT format (dates as YYYY-MM-DD):\n"
            f"COACH_SINCE: <appointment date>\n"
            f"STILL_IN_CHARGE: YES or NO\n"
            f"COACH_UNTIL: <departure date if they left, or CURRENT if still in charge>"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            text = re.sub(r'\[\d+\]', '', text)

            result = {}
            still_in_charge = None
            for line in text.splitlines():
                line = line.strip().replace("*", "")
                if "COACH_SINCE" in line.upper():
                    m = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', line)
                    if m:
                        d = m.group(1)
                        result["coach_since"] = d if len(d) == 10 else d + "-01"
                elif "STILL_IN_CHARGE" in line.upper():
                    still_in_charge = "YES" in line.upper()
                elif "COACH_UNTIL" in line.upper():
                    if "CURRENT" in line.upper():
                        result["coach_until"] = None
                    else:
                        m = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', line)
                        if m:
                            d = m.group(1)
                            result["coach_until"] = d if len(d) == 10 else d + "-28"
            return result if result.get("coach_since") else None
        except Exception:
            return None

    async def search_player_context(
        self, player_name: str, team: str, league: str, season_year: str | None = None,
    ) -> str | None:
        """Search web for player's tactical role and team playing style.
        Returns free-text context to feed into AI analysis.
        """
        if not self._llm:
            return None

        if season_year and season_year != "2025":
            season_str = f"{season_year}/{int(season_year)+1}"
            # For historical seasons, also ask which club they were at
            prompt = (
                f"Football player {player_name}. Season {season_str}.\n\n"
                f"1) Which club did {player_name} play for in {season_str}? "
                f"If they transferred mid-season, state both clubs and when.\n"
                f"2) What was {player_name}'s tactical role and position at that club in {season_str}? "
                f"(e.g. box-to-box midfielder, inverted winger, deep-lying playmaker, pressing forward, etc.)\n"
                f"3) How did {team or 'that club'} play tactically in {season_str}? "
                f"Formation, style (possession / counter-attack / pressing), manager's approach.\n"
                f"4) Was {player_name} a starter, rotation player, or backup in {season_str}?\n\n"
                f"Reply in 5-10 sentences. Be specific about THIS season, not current."
            )
        else:
            season_str = "2025/2026"
            prompt = (
                f"Football player {player_name}, currently at {team} ({league}). Season {season_str}.\n\n"
                f"1) What is {player_name}'s tactical role and position at {team}? "
                f"(e.g. box-to-box midfielder, inverted winger, deep-lying playmaker, etc.)\n"
                f"2) How does {team} play tactically this season? "
                f"Formation, style (possession / counter-attack / pressing), manager's approach.\n"
                f"3) Is {player_name} a starter, rotation player, or key player?\n\n"
                f"Reply in 5-10 sentences. Be specific about THIS season."
            )

        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            # Clean Perplexity citations
            text = re.sub(r'\[\d+\]', '', text)
            return text
        except Exception:
            return None
