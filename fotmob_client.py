import asyncio
import re
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cachetools import TTLCache

from config import USER_AGENT

logger = logging.getLogger(__name__)

BASE = "https://www.fotmob.com"
HEADERS = {"User-Agent": USER_AGENT}


class FotmobClient:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._build_id: Optional[str] = None
        self._build_id_lock = asyncio.Lock()
        self._player_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 30)

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=20.0,
            )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Build ID ────────────────────────────────────────────────────

    async def _fetch_build_id(self) -> str:
        """Fetch current Next.js buildId from any FotMob page."""
        resp = await self._client.get(f"{BASE}/")
        resp.raise_for_status()
        match = re.search(r'"buildId"\s*:\s*"([^"]+)"', resp.text)
        if not match:
            raise RuntimeError("Cannot extract FotMob buildId")
        bid = match.group(1)
        logger.info("FotMob buildId: %s", bid)
        return bid

    async def _get_build_id(self, force_refresh: bool = False) -> str:
        async with self._build_id_lock:
            if self._build_id is None or force_refresh:
                self._build_id = await self._fetch_build_id()
            return self._build_id

    # ── Search ──────────────────────────────────────────────────────

    async def search_players(self, term: str, limit: int = 50) -> List[Dict[str, Any]]:
        resp = await self._client.get(
            f"{BASE}/api/data/search/suggest",
            params={"hits": limit, "lang": "en", "term": term},
        )
        resp.raise_for_status()
        data = resp.json()
        if not data or not isinstance(data, list):
            return []
        suggestions = data[0].get("suggestions", [])
        return [s for s in suggestions if s.get("type") == "player"]

    # ── Player data via Next.js route ───────────────────────────────

    async def get_player(self, player_id: int, player_name: str = "player") -> Optional[Dict]:
        cached = self._player_cache.get(player_id)
        if cached:
            return cached

        slug = re.sub(r'[^a-z0-9]+', '-', player_name.lower()).strip('-') or "player"
        data = await self._fetch_player_nextjs(player_id, slug)
        if data:
            self._player_cache[player_id] = data
        return data

    async def _fetch_player_nextjs(self, player_id: int, slug: str) -> Optional[Dict]:
        """Fetch player data via _next/data route. Retries once with fresh buildId on failure."""
        for attempt in range(2):
            build_id = await self._get_build_id(force_refresh=(attempt > 0))
            url = f"{BASE}/_next/data/{build_id}/players/{player_id}/{slug}.json"
            resp = await self._client.get(url)

            if resp.status_code == 404 and attempt == 0:
                logger.warning("buildId stale, refreshing...")
                continue
            if resp.status_code != 200:
                logger.error("FotMob player %d: HTTP %d", player_id, resp.status_code)
                return None

            body = resp.json()
            page_props = body.get("pageProps", {})
            fallback = page_props.get("fallback", {})
            # Player data is under key "player:{id}"
            player_data = fallback.get(f"player:{player_id}")
            if player_data:
                return player_data
            # Fallback: try "data" key
            data = page_props.get("data")
            if data and isinstance(data, dict) and data.get("id"):
                return data
            return None
        return None
