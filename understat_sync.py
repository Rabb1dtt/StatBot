import asyncio
import logging

from understatapi import UnderstatClient

from database import PlayerDB

logger = logging.getLogger(__name__)

LEAGUES = ["EPL", "La_Liga", "Serie_A", "Bundesliga", "Ligue_1", "RFPL"]
CURRENT_SEASON = "2025"


def sync_player_ids(db: PlayerDB, season: str = CURRENT_SEASON) -> int:
    """Load all player IDs + names from Understat into DB. ~3100 players, 6 requests."""
    total = 0
    with UnderstatClient() as usc:
        for league in LEAGUES:
            try:
                players = usc.league(league=league).get_player_data(season=season)
                if isinstance(players, list):
                    count = db.upsert_players(players, league)
                    total += count
                    logger.info("Synced %s: %d players", league, count)
            except Exception:
                logger.exception("Failed to sync %s", league)
    logger.info("ID sync complete: %d players total", total)
    return total


async def sync_player_ids_async(db: PlayerDB, season: str = CURRENT_SEASON) -> int:
    return await asyncio.to_thread(sync_player_ids, db, season)
