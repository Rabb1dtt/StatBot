import logging
import sqlite3
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "players.db"


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _make_search_name(name: str) -> str:
    return _strip_accents(name).lower().strip()


class PlayerDB:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self) -> None:
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_tables(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS players (
                understat_id  INTEGER PRIMARY KEY,
                name          TEXT NOT NULL,
                name_search   TEXT NOT NULL,
                team          TEXT,
                league        TEXT,
                position      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_name_search ON players(name_search);
        """)

    def upsert_players(self, players: List[Dict], league: str) -> int:
        rows = []
        for p in players:
            name = p.get("player_name", "")
            rows.append((
                int(p["id"]),
                name,
                _make_search_name(name),
                p.get("team_title", ""),
                league,
                p.get("position", ""),
            ))
        self.conn.executemany("""
            INSERT INTO players (understat_id, name, name_search, team, league, position)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(understat_id) DO UPDATE SET
                name=excluded.name,
                name_search=excluded.name_search,
                team=excluded.team,
                league=excluded.league,
                position=excluded.position
        """, rows)
        self.conn.commit()
        return len(rows)

    def get_all_players(self) -> List[Dict]:
        cursor = self.conn.execute(
            "SELECT understat_id, name, name_search, team, league, position FROM players"
        )
        return [dict(row) for row in cursor.fetchall()]

    def player_count(self) -> int:
        cursor = self.conn.execute("SELECT COUNT(*) as cnt FROM players")
        return cursor.fetchone()["cnt"]

    def is_empty(self) -> bool:
        return self.player_count() == 0
