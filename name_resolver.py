import asyncio
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

    async def resolve(self, query: str) -> Optional[ResolvedPlayer]:
        """Resolve a player name query to a ResolvedPlayer."""
        results = self._fuzzy_search(query)
        if results:
            best = results[0]
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
                results = self._fuzzy_search(guess)
                if results:
                    best = results[0]
                    return ResolvedPlayer(
                        understat_id=best["understat_id"],
                        name=best["name"],
                        team=best.get("team", ""),
                        league=best.get("league", ""),
                        position=best.get("position", ""),
                    )

        return None

    async def parse_query(self, query: str) -> dict:
        """
        Determine if user wants single player or comparison.
        Returns: {"type": "single"|"compare", "names": [...]}
        """
        if not self._llm:
            return {"type": "single", "names": [query]}

        prompt = (
            "User sent a football query. Determine if they want:\n"
            "1) Stats for ONE player → type=single\n"
            "2) COMPARISON of TWO players → type=compare\n\n"
            "Comparison indicators: 'vs', 'или', 'против', 'сравни', 'compare', "
            "two names separated by comma/dash/и, etc.\n\n"
            "Reply STRICTLY in this format (no extra text):\n"
            "TYPE: single\n"
            "PLAYER1: <name as written by user>\n\n"
            "or for comparison:\n"
            "TYPE: compare\n"
            "PLAYER1: <first player name>\n"
            "PLAYER2: <second player name>\n\n"
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
                elif line.upper().startswith("PLAYER1:"):
                    names.append(line.split(":", 1)[1].strip())
                elif line.upper().startswith("PLAYER2:"):
                    names.append(line.split(":", 1)[1].strip())

            if names:
                return {"type": qtype, "names": names}
            return {"type": "single", "names": [query]}
        except Exception:
            return {"type": "single", "names": [query]}

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
