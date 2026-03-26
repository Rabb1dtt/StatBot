import asyncio
from typing import Any, Dict, List, Optional, Tuple

import httpx
from cachetools import TTLCache

from config import USER_AGENT


class FotmobClient:
    """
    Minimal async client for FotMob public endpoints used here:
    - /api/data/search/suggest (player search)
    - /api/data/playerData (player stats)
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self._player_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 30)
        self._advanced_cache: TTLCache = TTLCache(maxsize=2048, ttl=60 * 45)

    async def start(self) -> None:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url="https://www.fotmob.com/api",
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
                timeout=20.0,
            )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None:
                await self.start()
        assert self._client is not None
        return self._client

    async def _request_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Any:
        client = await self._ensure_client()
        for attempt in range(max_retries):
            resp = await client.get(path, params=params)
            if resp.status_code in {429, 500, 502, 503, 504}:
                delay = 0.7 * (2 ** attempt)
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp.json()
        resp.raise_for_status()
        return resp.json()

    async def search_players(self, term: str, limit: int = 50) -> List[Dict[str, Any]]:
        data = await self._request_json(
            "/data/search/suggest",
            params={"hits": limit, "lang": "en", "term": term},
        )
        if not data or not isinstance(data, list):
            return []
        suggestions = data[0].get("suggestions", [])
        return [s for s in suggestions if s.get("type") == "player"]

    async def fetch_player_data(self, player_id: int) -> Dict[str, Any]:
        cached = self._player_cache.get(player_id)
        if cached:
            return cached
        data = await self._request_json("/data/playerData", params={"id": player_id})
        self._player_cache[player_id] = data
        return data

    async def get_current_season_tournament_stats(
        self, player_id: int
    ) -> Tuple[Optional[str], List[Dict[str, Any]]]:
        """
        Returns (season_name, tournament_stats_for_that_season)
        season_name: str like '2025/2026'
        tournament_stats: list of dicts with goals/assists/appearances etc.
        """
        data = await self.fetch_player_data(player_id)
        stat_seasons = data.get("statSeasons") or []
        if not stat_seasons:
            return None, []
        current_season = stat_seasons[0].get("seasonName")

        tournaments = self._find_tournament_stats(data)
        filtered = [
            t for t in tournaments if t.get("seasonName") == current_season
        ]
        return current_season, filtered

    async def get_player_advanced_stats(self, player_id: int) -> Dict[str, Any]:
        cached = self._advanced_cache.get(player_id)
        if cached:
            return cached

        data = await self.fetch_player_data(player_id)
        position = self._normalize_position(data.get("positionDescription"))
        is_goalkeeper = (position or "").lower().startswith("goalkeeper")

        first_season_stats = data.get("firstSeasonStats") or {}
        stat_items = self._collect_stat_items(first_season_stats)

        minutes = self._extract_metric(
            stat_items,
            key_candidates={"minutes_played"},
            title_candidates={"minutes"},
        )

        metrics = self._extract_metrics(stat_items, is_goalkeeper)

        # If GK stats are missing, try scanning the entire payload
        if is_goalkeeper and self._metrics_only_cards(metrics):
            all_items = self._collect_stat_items(data)
            minutes = minutes or self._extract_metric(
                all_items, {"minutes_played"}, {"minutes"}
            )
            metrics = self._extract_metrics(all_items, is_goalkeeper)
            if self._metrics_only_cards(metrics):
                # avoid showing only cards for GK
                metrics = {}

        result = {
            "position": position,
            "is_goalkeeper": is_goalkeeper,
            "minutes": minutes,
            "metrics": metrics,
        }
        self._advanced_cache[player_id] = result
        return result

    def _collect_stat_items(self, obj: Any) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        if isinstance(obj, dict):
            if "items" in obj and isinstance(obj["items"], list):
                items.extend(obj["items"])
            for v in obj.values():
                items.extend(self._collect_stat_items(v))
        elif isinstance(obj, list):
            for v in obj:
                items.extend(self._collect_stat_items(v))
        return items

    def _extract_metrics(self, items: List[Dict[str, Any]], is_goalkeeper: bool) -> Dict[str, float]:
        metrics: Dict[str, float] = {}

        def add(key: str, value: Optional[float]) -> None:
            if value is None:
                return
            metrics[key] = value

        # Outfield
        add("xg", self._extract_metric(items, {"expected_goals"}, {"xg"}))
        add("xa", self._extract_metric(items, {"expected_assists"}, {"xa"}))
        add("xgot", self._extract_metric(items, {"expected_goals_on_target", "expected_goalsontarget"}, {"xgot"}))
        add("shots", self._extract_metric(items, {"shots"}, {"shots"}))
        add("shots_on_target", self._extract_metric(items, {"shotsontarget", "shots_on_target", "ShotsOnTarget"}, {"shots on target"}))
        add("big_chances_created", self._extract_metric(items, {"big_chances_created"}, {"big chances created"}))
        add("big_chances_missed", self._extract_metric(items, {"big_chances_missed"}, {"big chances missed"}))
        add("accurate_passes", self._extract_metric(items, {"successful_passes"}, {"accurate passes"}))
        add("tackles", self._extract_metric(items, {"matchstats.headers.tackles", "tackles"}, {"tackles"}))
        add("interceptions", self._extract_metric(items, {"interceptions"}, {"interceptions"}))
        add("clearances", self._extract_metric(items, {"clearances"}, {"clearances"}))
        add("blocks", self._extract_metric(items, {"blocks"}, {"blocks"}))
        add(
            "poss_won_att_3rd",
            self._extract_metric(items, {"poss_won_att_3rd_team_title"}, {"possession won final 3rd"}),
        )
        add("fouls_committed", self._extract_metric(items, {"fouls"}, {"fouls committed"}))
        add("yellow_cards", self._extract_metric(items, {"yellow_cards"}, {"yellow cards"}))
        add("red_cards", self._extract_metric(items, {"red_cards"}, {"red cards"}))

        # Goalkeeper specific (only if present)
        if is_goalkeeper:
            add("goals_prevented", self._extract_metric(items, {"goals_prevented"}, {"goals prevented"}))
            add("saves", self._extract_metric(items, {"saves"}, {"saves"}))
            add("clean_sheets", self._extract_metric(items, {"clean_sheets"}, {"clean sheets"}))
            add("goals_conceded", self._extract_metric(items, {"goals_conceded"}, {"goals conceded"}))

            # fallback keyword scan
            self._extract_by_keyword(items, metrics)

            # only show cards if we have other GK stats
            if self._metrics_only_cards(metrics):
                metrics.pop("yellow_cards", None)
                metrics.pop("red_cards", None)

        return metrics

    def _extract_metric(
        self,
        items: List[Dict[str, Any]],
        key_candidates: set[str],
        title_candidates: set[str],
    ) -> Optional[float]:
        key_candidates_lower = {k.lower() for k in key_candidates}
        title_candidates_lower = {t.lower() for t in title_candidates}
        for item in items:
            key = str(item.get("localizedTitleId", "")).lower()
            title = str(item.get("title", "")).lower()
            if key in key_candidates_lower or title in title_candidates_lower:
                return self._parse_number(item.get("statValue"))
        return None

    def _normalize_position(self, raw: Any) -> Optional[str]:
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        if isinstance(raw, dict):
            primary = raw.get("primaryPosition")
            if isinstance(primary, dict):
                label = primary.get("label")
                if isinstance(label, str):
                    return label
            label = raw.get("label")
            if isinstance(label, str):
                return label
        return str(raw)

    def _parse_number(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).replace(",", ".")
            return float(text)
        except Exception:
            return None

    def _extract_by_keyword(self, items: List[Dict[str, Any]], metrics: Dict[str, float]) -> None:
        """
        For GK stats some providers use different keys.
        Try to discover core GK fields by keyword in title/localizedTitleId.
        """
        keyword_map = {
            "saves": ["save"],
            "clean_sheets": ["clean sheet", "clean sheets"],
            "goals_conceded": ["goals conceded", "conceded"],
            "goals_prevented": ["goals prevented", "prevented"],
        }
        for item in items:
            key = str(item.get("localizedTitleId", "")).lower()
            title = str(item.get("title", "")).lower()
            value = self._parse_number(item.get("statValue"))
            if value is None:
                continue
            for target, keywords in keyword_map.items():
                if target in metrics:
                    continue
                if any(k in key or k in title for k in keywords):
                    metrics[target] = value
                    break

    def _metrics_only_cards(self, metrics: Dict[str, float]) -> bool:
        if not metrics:
            return True
        keys = set(metrics.keys())
        return keys.issubset({"yellow_cards", "red_cards"})

    def _find_tournament_stats(self, obj: Any) -> List[Dict[str, Any]]:
        """Recursively look for 'tournamentStats' in the player payload."""
        if isinstance(obj, dict):
            if "tournamentStats" in obj:
                ts = obj.get("tournamentStats")
                return ts or []
            for v in obj.values():
                res = self._find_tournament_stats(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for v in obj:
                res = self._find_tournament_stats(v)
                if res:
                    return res
        return []
