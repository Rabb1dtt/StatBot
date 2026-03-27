import asyncio
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, List, Dict

import cyrtranslit
from rapidfuzz import fuzz
from cachetools import TTLCache

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

import config
from fotmob_client import FotmobClient


@dataclass
class ResolvedPlayer:
    player_id: int
    name: str
    team: Optional[str]
    score: float


def _normalize(text: str) -> str:
    return text.lower().strip()


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _expand_queries(query: str) -> List[str]:
    q = query.strip()
    variants: List[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v not in variants:
            variants.append(v)

    add(q)
    add(q.replace("-", " "))
    add(q.replace(" ", "-"))

    translit = cyrtranslit.to_latin(q, "ru")
    add(translit)
    add(translit.replace("-", " "))
    add(_strip_accents(translit))

    parts = re.split(r"\s+", q)
    if len(parts) > 1:
        add(parts[-1])

    return variants[:8]


class NameResolver:
    def __init__(self, client: FotmobClient) -> None:
        self.client = client
        if OpenAI and config.OPENROUTER_API_KEY:
            self._llm = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.OPENROUTER_API_KEY,
            )
        else:
            self._llm = None
        self.model = config.OPENROUTER_MODEL
        self._cache: TTLCache = TTLCache(maxsize=4096, ttl=60 * 60 * 24)

    async def resolve(self, query: str) -> Optional[ResolvedPlayer]:
        cached = self._cache.get(query.lower())
        if cached:
            return cached

        candidates: List[Dict] = []
        queries = _expand_queries(query)

        for q in queries:
            players = await self.client.search_players(q)
            candidates.extend(players)

        # LLM fallback if nothing found
        if not candidates and self._llm:
            guess = await self._guess_latin_name(query)
            if guess:
                players = await self.client.search_players(guess)
                candidates.extend(players)

        if not candidates:
            return None

        best = self._choose_best(query, candidates)
        if best is None:
            return None

        resolved = ResolvedPlayer(
            player_id=int(best["id"]),
            name=best["name"],
            team=best.get("teamName"),
            score=best["_score"],
        )
        self._cache[query.lower()] = resolved
        return resolved

    def _choose_best(self, query: str, candidates: List[Dict]) -> Optional[Dict]:
        normalized = _normalize(cyrtranslit.to_latin(query, "ru"))
        best = None
        best_score = -1.0
        for c in candidates:
            name = c.get("name", "")
            score = fuzz.WRatio(normalized, _normalize(name))
            combined = score * 0.7 + (c.get("score", 0) / 400_000) * 30
            if combined > best_score:
                best_score = combined
                best = c
        if best:
            best["_score"] = best_score
        return best

    async def parse_query(self, query: str) -> dict:
        """
        Parse user query to determine intent.
        Returns: {"type": "single", "names": ["Salah"]}
             or: {"type": "compare", "names": ["Salah", "Mbappe"]}
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
            "PLAYER1: <first player name as written>\n"
            "PLAYER2: <second player name as written>\n\n"
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
            result: dict = {"type": "single", "names": [query]}
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
                result = {"type": qtype, "names": names}
            return result
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
