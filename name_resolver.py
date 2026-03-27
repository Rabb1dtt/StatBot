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

        # Sort by score descending
        sorted_results = sorted(best_results.values(), key=lambda x: x[0], reverse=True)
        return [p for _, p in sorted_results[:limit]]

    def _pick_best(self, results: List[Dict], team_hint: Optional[str] = None) -> Optional[Dict]:
        """Pick the best result, boosting matches with team_hint."""
        if not results:
            return None
        if not team_hint or len(results) == 1:
            return results[0]

        # Transliterate hint for matching
        hint_lower = _normalize(team_hint)
        hint_latin = _normalize(_transliterate(team_hint))

        for r in results:
            team = _normalize(r.get("team", ""))
            if hint_lower in team or hint_latin in team or team in hint_lower or team in hint_latin:
                return r
        # No team match — return first (best fuzzy)
        return results[0]

    async def resolve(self, query: str, team_hint: Optional[str] = None) -> Optional[ResolvedPlayer]:
        """Resolve a player name query to a ResolvedPlayer.
        team_hint: optional team name from parentheses, e.g. 'Реал Мадрид'.
        """
        results = self._fuzzy_search(query, limit=10)
        best = self._pick_best(results, team_hint)
        if best:
            return ResolvedPlayer(
                understat_id=best["understat_id"],
                name=best["name"],
                team=best.get("team", ""),
                league=best.get("league", ""),
                position=best.get("position", ""),
            )

        # LLM fallback: transliterate/guess the name
        if self._llm:
            guess = await self._guess_latin_name(query)
            if guess:
                results = self._fuzzy_search(guess, limit=10)
                best = self._pick_best(results, team_hint)
                if best:
                    return ResolvedPlayer(
                        understat_id=best["understat_id"],
                        name=best["name"],
                        team=best.get("team", ""),
                        league=best.get("league", ""),
                        position=best.get("position", ""),
                    )

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
        Determine if user wants single player or comparison.
        Returns: {"type": "single"|"compare", "names": [...]}
        """
        # Try fast regex first
        fast = self._try_fast_split(query)
        if fast:
            return fast

        if not self._llm:
            return {"type": "single", "names": [query]}

        prompt = (
            "User sent a football query. Determine if they want:\n"
            "1) Stats for ONE player → type=single\n"
            "2) COMPARISON of MULTIPLE players (2-5) → type=compare\n\n"
            "Comparison indicators: 'vs', 'или', 'против', 'сравни', 'compare', "
            "multiple names separated by comma/dash/и/vs, etc.\n\n"
            "Reply STRICTLY in this format (no extra text):\n"
            "TYPE: single\n"
            "PLAYER1: <name>\n\n"
            "or for comparison (up to 5 players):\n"
            "TYPE: compare\n"
            "PLAYER1: <first player name>\n"
            "PLAYER2: <second player name>\n"
            "PLAYER3: <third player name>\n"
            "(add PLAYER4, PLAYER5 if needed, skip if not)\n\n"
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
            for line in text.splitlines():
                line = line.strip()
                if line.upper().startswith("TYPE:"):
                    val = line.split(":", 1)[1].strip().lower()
                    if val == "compare":
                        qtype = "compare"
                elif re.match(r'^PLAYER\d+:', line, re.IGNORECASE):
                    name = line.split(":", 1)[1].strip()
                    if name:
                        names.append(name)

            if names:
                return {"type": qtype, "names": names, "team_hints": [None] * len(names)}
            return {"type": "single", "names": [query], "team_hints": [None]}
        except Exception:
            return {"type": "single", "names": [query], "team_hints": [None]}

    async def _guess_latin_name(self, query: str) -> Optional[str]:
        if not self._llm:
            return None
        prompt = (
            "Translate this football player query to Latin script name+surname. "
            "Reply with ONLY the name, nothing else.\n"
            f"Query: {query!r}"
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
