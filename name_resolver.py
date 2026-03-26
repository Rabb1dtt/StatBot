from dataclasses import dataclass
from typing import Optional, Tuple, List, Dict
import re
import unicodedata

import cyrtranslit
from rapidfuzz import fuzz
from cachetools import TTLCache

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional
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


def _slugify(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text.replace(" ", "-")


def _spaceify(text: str) -> str:
    return text.replace("-", " ")


def _expand_queries(query: str) -> List[str]:
    q = query.strip()
    variants: List[str] = []

    def add(v: str) -> None:
        v = v.strip()
        if v and v not in variants:
            variants.append(v)

    add(q)
    add(_spaceify(q))
    add(_slugify(q))

    translit = cyrtranslit.to_latin(q, "ru")
    add(translit)
    add(_spaceify(translit))
    add(_slugify(translit))
    add(_strip_accents(translit))
    add(_slugify(_strip_accents(translit)))

    # also try last token (surname)
    parts = re.split(r"\s+", q)
    if len(parts) > 1:
        add(parts[-1])
        add(_slugify(parts[-1]))

    return variants[:10]


class NameResolver:
    def __init__(self, client: FotmobClient) -> None:
        self.client = client
        self._openai_client = OpenAI(api_key=config.OPENAI_API_KEY) if config.OPENAI_API_KEY else None
        self.model = config.OPENAI_MODEL
        self._cache: TTLCache = TTLCache(maxsize=4096, ttl=60 * 60 * 24)

    async def resolve(self, query: str) -> Optional[ResolvedPlayer]:
        cached = self._cache.get(query.lower())
        if cached:
            return cached
        candidates: List[Dict] = []
        queries = _expand_queries(query)

        # primary search attempts
        for q in queries:
            players = await self.client.search_players(q)
            candidates.extend(players)

        # optional LLM aid when nothing matched
        if not candidates and self._openai_client:
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
            score=best["score_value"],
        )
        self._cache[query.lower()] = resolved
        return resolved

    def _choose_best(self, query: str, candidates: List[Dict]) -> Optional[Dict]:
        normalized_query = _normalize(cyrtranslit.to_latin(query, "ru"))
        best_candidate = None
        best_score = -1.0
        for cand in candidates:
            name = cand.get("name", "")
            score = fuzz.WRatio(normalized_query, _normalize(name))
            # prefer Fotmob's own score too
            combined = score * 0.7 + (cand.get("score", 0) / 400_000) * 30
            if combined > best_score:
                best_score = combined
                best_candidate = cand
        if best_candidate:
            best_candidate["score_value"] = best_score
        return best_candidate

    async def _guess_latin_name(self, query: str) -> Optional[str]:
        if not self._openai_client:
            return None
        prompt = (
            "Преобразуй запрос пользователя о футболисте в латинскую транслитерацию "
            "имени и фамилии. Ответь только именем и фамилией, без кавычек. "
            f"Запрос: {query!r}"
        )
        try:
            resp = self._openai_client.responses.create(
                model=self.model,
                input=prompt,
            )
            text = resp.output_text.strip()
            return text
        except Exception:
            return None
