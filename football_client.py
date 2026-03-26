import asyncio
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cachetools import TTLCache

import config

# Top leagues to search across when no team is specified
TOP_LEAGUE_IDS = [
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    253,  # MLS
    203,  # Super Lig
    94,   # Primeira Liga
    88,   # Eredivisie
    144,  # Belgian Pro League
]

LATEST_SEASON = 2024  # Free plan: 2022-2024


class FootballClient:
    """Async client for API-Football v3."""

    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._player_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 60)
        self._team_cache: TTLCache = TTLCache(maxsize=512, ttl=60 * 60 * 24)

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.BASE_URL,
                headers={"x-apisports-key": config.API_FOOTBALL_KEY},
                follow_redirects=True,
                timeout=20.0,
            )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict:
        if self._client is None:
            await self.start()
        for attempt in range(3):
            resp = await self._client.get(path, params=params)
            resp.raise_for_status()
            data = resp.json()
            # Handle rate limiting
            if data.get("errors", {}).get("rateLimit"):
                await asyncio.sleep(10 * (attempt + 1))
                continue
            return data
        return data

    # ── Search ──────────────────────────────────────────────────────

    async def search_player(
        self, name: str, team_name: Optional[str] = None, season: int = LATEST_SEASON,
    ) -> Optional[Dict]:
        """
        Search for a player by name.
        If team_name is given, resolve team first (1 request), then search in that team (1 request).
        Otherwise search across top leagues (1 request per league, stops on first hit).
        Returns the first matching player dict with full statistics, or None.
        """
        # Strategy 1: search by team (most efficient — 2 API calls)
        if team_name:
            team_id = await self._resolve_team(team_name)
            if team_id:
                result = await self._search_in_context(name, season, team=team_id)
                if result:
                    return result

        # Strategy 2: search top 5 leagues only (save rate limit)
        for league_id in TOP_LEAGUE_IDS[:5]:
            result = await self._search_in_context(name, season, league=league_id)
            if result:
                return result

        return None

    async def _search_in_context(
        self, name: str, season: int, league: Optional[int] = None, team: Optional[int] = None,
    ) -> Optional[Dict]:
        params: Dict[str, Any] = {"search": name, "season": season}
        if league:
            params["league"] = league
        elif team:
            params["team"] = team
        else:
            return None

        data = await self._get("/players", params=params)
        results = data.get("response", [])
        if not results:
            return None

        # Pick best match (first result is usually best)
        return results[0]

    async def _resolve_team(self, team_name: str) -> Optional[int]:
        cached = self._team_cache.get(team_name.lower())
        if cached:
            return cached

        data = await self._get("/teams", params={"search": team_name})
        results = data.get("response", [])
        if not results:
            return None

        team_id = results[0]["team"]["id"]
        self._team_cache[team_name.lower()] = team_id
        return team_id

    # ── Get player by ID ────────────────────────────────────────────

    async def get_player_by_id(self, player_id: int, season: int = LATEST_SEASON) -> Optional[Dict]:
        cached = self._player_cache.get((player_id, season))
        if cached:
            return cached

        data = await self._get("/players", params={"id": player_id, "season": season})
        results = data.get("response", [])
        if not results:
            return None

        result = results[0]
        self._player_cache[(player_id, season)] = result
        return result
