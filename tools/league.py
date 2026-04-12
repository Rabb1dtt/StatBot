"""League tools for the orchestrator."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def get_league_standings(
    league: str,
    clients: dict[str, Any],
    season_year: str = "",
) -> str:
    """Get top-10 league standings table."""
    sofa = clients["sofa"]
    standings = await sofa.get_league_top10(league, season_year=season_year or None)
    if not standings:
        return f"No standings found for league '{league}'."
    return standings
