import asyncio
import logging
from typing import Dict, List, Optional

from understatapi import UnderstatClient
from cachetools import TTLCache

logger = logging.getLogger(__name__)

CACHE_TTL = 24 * 60 * 60  # 24 hours


class UnderstatPlayerClient:
    """Fetches per-player stats on demand, caches for 24h."""

    def __init__(self) -> None:
        self._season_cache: TTLCache = TTLCache(maxsize=2048, ttl=CACHE_TTL)
        self._match_cache: TTLCache = TTLCache(maxsize=512, ttl=CACHE_TTL)

    def _get_season_data(self, player_id: int) -> List[Dict]:
        with UnderstatClient() as usc:
            data = usc.player(player=str(player_id)).get_season_data()
        # data is {"season": [...]} or similar
        if isinstance(data, dict):
            return data.get("season", [])
        return data if isinstance(data, list) else []

    def _get_match_data(self, player_id: int) -> List[Dict]:
        with UnderstatClient() as usc:
            data = usc.player(player=str(player_id)).get_match_data()
        if isinstance(data, dict):
            return data.get("match", data.get("matches", []))
        return data if isinstance(data, list) else []

    async def get_season_stats(self, player_id: int) -> List[Dict]:
        """Get all season stats for a player (all seasons). Cached 24h."""
        cached = self._season_cache.get(player_id)
        if cached is not None:
            return cached
        result = await asyncio.to_thread(self._get_season_data, player_id)
        self._season_cache[player_id] = result
        return result

    async def get_current_season(self, player_id: int, season: str = "2025") -> Optional[Dict]:
        """Get stats for current season only."""
        seasons = await self.get_season_stats(player_id)
        for s in seasons:
            if str(s.get("season")) == season:
                return s
        # If exact season not found, return the most recent one
        return seasons[0] if seasons else None

    async def get_match_stats(self, player_id: int) -> List[Dict]:
        """Get per-match data. Cached 24h."""
        cached = self._match_cache.get(player_id)
        if cached is not None:
            return cached
        result = await asyncio.to_thread(self._get_match_data, player_id)
        self._match_cache[player_id] = result
        return result
