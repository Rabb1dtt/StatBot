import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

BASE = "https://api.sofascore.com/api/v1"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# league name -> unique_tournament_id
LEAGUE_TOURNAMENT_IDS = {
    "EPL": 17,
    "La_Liga": 8,
    "Serie_A": 23,
    "Bundesliga": 35,
    "Ligue_1": 34,
    "RFPL": 203,
}

CACHE_TTL = 24 * 60 * 60  # 24 hours


class SofascoreClient:
    """Fetches detailed player stats (dribbling, duels, etc.) from SofaScore API."""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._stats_cache: TTLCache = TTLCache(maxsize=2048, ttl=CACHE_TTL)
        self._id_cache: TTLCache = TTLCache(maxsize=2048, ttl=CACHE_TTL)
        self._season_cache: Dict[int, int] = {}  # tournament_id -> season_id

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE, headers=HEADERS,
                follow_redirects=True, timeout=15.0,
            )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, path: str) -> Optional[Dict]:
        if self._client is None:
            await self.start()
        try:
            resp = await self._client.get(path)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception:
            logger.exception("SofaScore request failed: %s", path)
            return None

    async def search_player(self, name: str) -> Optional[Dict]:
        """Search for a player by name, return first result."""
        cached = self._id_cache.get(name.lower())
        if cached:
            return cached

        data = await self._get(f"/search/players?q={name}")
        if not data:
            return None
        results = data.get("results", [])
        if not results:
            return None

        player = results[0].get("entity", {})
        self._id_cache[name.lower()] = player
        return player

    async def _get_current_season(self, tournament_id: int) -> Optional[int]:
        """Get current season ID for a tournament."""
        if tournament_id in self._season_cache:
            return self._season_cache[tournament_id]

        data = await self._get(f"/unique-tournament/{tournament_id}/seasons")
        if not data:
            return None
        seasons = data.get("seasons", [])
        if not seasons:
            return None

        season_id = seasons[0]["id"]
        self._season_cache[tournament_id] = season_id
        return season_id

    async def get_player_stats(
        self, player_name: str, league: str,
    ) -> Optional[Dict]:
        """Get detailed season stats for a player."""
        cache_key = f"{player_name}:{league}"
        cached = self._stats_cache.get(cache_key)
        if cached is not None:
            return cached

        # Find player
        player = await self.search_player(player_name)
        if not player:
            return None

        player_id = player["id"]

        # Get tournament/season IDs
        ut_id = LEAGUE_TOURNAMENT_IDS.get(league)
        if not ut_id:
            return None

        season_id = await self._get_current_season(ut_id)
        if not season_id:
            return None

        data = await self._get(
            f"/player/{player_id}/unique-tournament/{ut_id}/season/{season_id}/statistics/overall"
        )
        if not data:
            return None

        stats = data.get("statistics", {})
        self._stats_cache[cache_key] = stats
        return stats


def format_sofascore_extra(stats: Dict) -> str:
    """Format SofaScore stats into a dribbling/duels block for AI."""
    if not stats:
        return ""

    lines = []
    lines.append("*Дриблинг и единоборства (SofaScore):*")

    # Dribbling
    succ = stats.get("successfulDribbles")
    total = stats.get("totalContest")
    pct = stats.get("successfulDribblesPercentage")
    if succ is not None and total is not None:
        lines.append(f"  Обводки: {succ}/{total} успешных ({pct:.1f}%)" if pct else f"  Обводки: {succ}/{total}")

    disp = stats.get("dispossessed")
    if disp is not None:
        lines.append(f"  Потери мяча при обводке: {disp}")

    # Possession
    poss_won = stats.get("possessionWonAttThird")
    if poss_won is not None:
        lines.append(f"  Отборы в атакующей трети: {poss_won}")

    poss_lost = stats.get("possessionLost")
    if poss_lost is not None:
        lines.append(f"  Всего потерь владения: {poss_lost}")

    # Duels
    ground_won = stats.get("groundDuelsWon")
    ground_pct = stats.get("groundDuelsWonPercentage")
    if ground_won is not None:
        lines.append(f"  Наземные единоборства: {ground_won} выиграно ({ground_pct:.1f}%)" if ground_pct else f"  Наземные единоборства: {ground_won}")

    aerial_won = stats.get("aerialDuelsWon")
    aerial_pct = stats.get("aerialDuelsWonPercentage")
    if aerial_won is not None:
        lines.append(f"  Воздушные единоборства: {aerial_won} выиграно ({aerial_pct:.1f}%)" if aerial_pct else f"  Воздушные: {aerial_won}")

    # Big chances
    bc_created = stats.get("bigChancesCreated")
    bc_missed = stats.get("bigChancesMissed")
    if bc_created is not None or bc_missed is not None:
        parts = []
        if bc_created is not None:
            parts.append(f"создано {bc_created}")
        if bc_missed is not None:
            parts.append(f"упущено {bc_missed}")
        lines.append(f"  Голевые моменты: {', '.join(parts)}")

    # Touches breakdown
    touches = stats.get("touches")
    att_third = stats.get("shotsFromInsideTheBox")
    if touches:
        lines.append(f"  Касания: {touches}")

    # Shots breakdown
    shots_in = stats.get("shotsFromInsideTheBox")
    shots_out = stats.get("shotsFromOutsideTheBox")
    if shots_in is not None or shots_out is not None:
        lines.append(f"  Удары из штрафной: {shots_in or 0} | Из-за штрафной: {shots_out or 0}")

    # Goals breakdown
    goals_in = stats.get("goalsFromInsideTheBox")
    goals_out = stats.get("goalsFromOutsideTheBox")
    if goals_in is not None:
        lines.append(f"  Голы из штрафной: {goals_in} | Издалека: {goals_out or 0}")

    if len(lines) <= 1:
        return ""
    return "\n".join(lines)
