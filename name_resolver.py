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
        self.model = config.OPENROUTER_MODEL

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
        """Detect match analysis queries like 'Салах против Реала' or 'Мбаппе последний матч'."""
        q = query.strip()

        # "Салах последний матч" / "Мбаппе last match" / "Холанд вчера"
        last_match = re.match(
            r'^(.+?)\s+(?:последний матч|last match|вчера|yesterday|сегодня|today)$',
            q, flags=re.IGNORECASE,
        )
        if last_match:
            return {
                "type": "match",
                "names": [self._clean_name(last_match.group(1))],
                "team_hints": [self._extract_team_hint(last_match.group(1))],
                "opponent": None,
            }

        # "как сыграл Салах против Реала" / "Салах против Арсенала" / "Мбаппе vs Барселона матч"
        vs_match = re.match(
            r'^(?:как\s+(?:сыграл|играл)\s+)?(.+?)\s+(?:против|vs\.?|versus)\s+(.+?)(?:\s+(?:матч|match))?$',
            q, flags=re.IGNORECASE,
        )
        if vs_match:
            player_raw = vs_match.group(1).strip()
            opponent = vs_match.group(2).strip()
            return {
                "type": "match",
                "names": [self._clean_name(player_raw)],
                "team_hints": [self._extract_team_hint(player_raw)],
                "opponent": opponent,
            }

        # "матч Салах Реал" / "match Mbappe Barcelona"
        match_prefix = re.match(
            r'^(?:матч|match)\s+(.+?)\s+(?:против|vs\.?|versus|—|-)\s+(.+)$',
            q, flags=re.IGNORECASE,
        )
        if match_prefix:
            return {
                "type": "match",
                "names": [self._clean_name(match_prefix.group(1))],
                "team_hints": [self._extract_team_hint(match_prefix.group(1))],
                "opponent": match_prefix.group(2).strip(),
            }

        return None

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
        Determine query type: single, compare, or match.
        Returns: {"type": "single"|"compare"|"match", "names": [...], ...}
        """
        # Try match query first (highest priority)
        match_q = self._try_match_query(query)
        if match_q:
            return match_q

        # Try comparison
        fast = self._try_fast_split(query)
        if fast:
            return fast

        if not self._llm:
            return {"type": "single", "names": [query]}

        prompt = (
            "User sent a football query. Determine the type:\n"
            "1) type=single — stats for ONE player for the season\n"
            "2) type=compare — COMPARISON of 2-5 players\n"
            "3) type=match — analysis of a player in SPECIFIC MATCH(ES) vs an opponent\n\n"
            "For type=match, also extract:\n"
            "- OPPONENT: team name (or NONE if 'last match')\n"
            "- TOURNAMENT: tournament filter (e.g. 'Champions League', 'Premier League', 'FA Cup', or ALL)\n"
            "- COUNT: number of matches to show (e.g. 2, or ALL)\n"
            "- ALL_TIME: yes if user wants career history, no if current season only\n\n"
            "Examples:\n"
            "- 'Хусанов последние 2 матча против Реала в ЛЧ' → match, OPPONENT: Real Madrid, TOURNAMENT: Champions League, COUNT: 2\n"
            "- 'Фоден против МЮ в лиге' → match, OPPONENT: Manchester United, TOURNAMENT: Premier League, COUNT: ALL\n"
            "- 'Фоден против МЮ за карьеру' → match, OPPONENT: Manchester United, TOURNAMENT: ALL, COUNT: ALL, ALL_TIME: yes\n"
            "- 'Салах последний матч' → match, OPPONENT: NONE, COUNT: 1\n"
            "- 'сравни Салаха и Мбаппе' → compare\n"
            "- 'Холанд' → single\n\n"
            "Reply STRICTLY in this format:\n"
            "TYPE: single|compare|match\n"
            "PLAYER1: <name>\n"
            "(PLAYER2: <name> — for compare only)\n"
            "OPPONENT: <team> or NONE\n"
            "TOURNAMENT: <name> or ALL\n"
            "COUNT: <number> or ALL\n"
            "ALL_TIME: yes or no\n\n"
            f"Query: {query}"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()

            text = await asyncio.to_thread(_call)
            qtype = "single"
            names = []
            opponent = None
            tournament = None
            count = None
            all_time = False

            for line in text.splitlines():
                line = line.strip()
                if line.upper().startswith("TYPE:"):
                    val = line.split(":", 1)[1].strip().lower()
                    if val in ("compare", "match"):
                        qtype = val
                elif re.match(r'^PLAYER\d+:', line, re.IGNORECASE):
                    name = line.split(":", 1)[1].strip()
                    if name:
                        names.append(name)
                elif line.upper().startswith("OPPONENT:"):
                    val = line.split(":", 1)[1].strip()
                    if val.upper() != "NONE":
                        opponent = val
                elif line.upper().startswith("TOURNAMENT:"):
                    val = line.split(":", 1)[1].strip()
                    if val.upper() != "ALL":
                        tournament = val
                elif line.upper().startswith("COUNT:"):
                    val = line.split(":", 1)[1].strip()
                    if val.upper() != "ALL":
                        try:
                            count = int(val)
                        except ValueError:
                            pass
                elif line.upper().startswith("ALL_TIME:"):
                    val = line.split(":", 1)[1].strip().lower()
                    all_time = val in ("yes", "да", "true")

            if not names:
                return {"type": "single", "names": [query], "team_hints": [None]}

            result = {
                "type": qtype,
                "names": names,
                "team_hints": [None] * len(names),
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
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            return await asyncio.to_thread(_call)
        except Exception:
            return None
