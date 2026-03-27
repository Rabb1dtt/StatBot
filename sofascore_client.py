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
        self._standings_cache: TTLCache = TTLCache(maxsize=32, ttl=CACHE_TTL)

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

        # Enrich with player profile data (positions)
        profile = await self._get(f"/player/{player_id}")
        if profile:
            p = profile.get("player", {})
            stats["_positions_detailed"] = p.get("positionsDetailed", [])
            stats["_position"] = p.get("position", "")

        self._stats_cache[cache_key] = stats
        return stats

    async def get_league_top10(self, league: str) -> Optional[str]:
        """Get top 10 standings for a league. Returns formatted text."""
        cached = self._standings_cache.get(league)
        if cached is not None:
            return cached

        ut_id = LEAGUE_TOURNAMENT_IDS.get(league)
        if not ut_id:
            return None

        season_id = await self._get_current_season(ut_id)
        if not season_id:
            return None

        data = await self._get(
            f"/unique-tournament/{ut_id}/season/{season_id}/standings/total"
        )
        if not data:
            return None

        standings = data.get("standings", [])
        if not standings:
            return None

        rows = standings[0].get("rows", [])
        lines = [f"*Таблица {league} (топ-10 текущий сезон):*"]
        for r in rows[:10]:
            t = r.get("team", {})
            name = t.get("name", "?")
            pos = r.get("position", "?")
            pts = r.get("points", 0)
            w = r.get("wins", 0)
            d = r.get("draws", 0)
            l = r.get("losses", 0)
            gf = r.get("scoresFor", 0)
            ga = r.get("scoresAgainst", 0)
            lines.append(f"  {pos}. {name} — {pts}pts ({w}W {d}D {l}L, {gf}-{ga})")

        result = "\n".join(lines)
        self._standings_cache[league] = result
        return result

    # ── Player tournaments & per-match stats ────────────────────────

    async def get_player_tournaments(self, player_id: int) -> List[Dict]:
        """Get all tournaments/seasons a player participated in."""
        data = await self._get(f"/player/{player_id}/statistics/seasons")
        if not data:
            return []
        result = []
        for entry in data.get("uniqueTournamentSeasons", []):
            ut = entry.get("uniqueTournament", {})
            for s in entry.get("seasons", []):
                result.append({
                    "tournament_id": ut.get("id"),
                    "tournament_name": ut.get("name", ""),
                    "season_id": s.get("id"),
                    "season_name": s.get("name", ""),
                })
        return result

    async def get_player_tournament_aggregate(
        self, player_id: int, tournament_id: int, season_id: int,
    ) -> Optional[Dict]:
        """Get aggregate stats for a player in a specific tournament/season."""
        data = await self._get(
            f"/player/{player_id}/unique-tournament/{tournament_id}/season/{season_id}/statistics/overall"
        )
        if not data:
            return None
        return data.get("statistics", {})

    async def get_player_events(self, player_id: int, page: int = 0) -> List[Dict]:
        """Get recent events (matches) for a player, sorted by date descending."""
        data = await self._get(f"/player/{player_id}/events/last/{page}")
        if not data:
            return []
        events = data.get("events", [])
        # SofaScore doesn't guarantee date order — sort by timestamp desc
        events.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)
        return events

    async def get_player_event_stats(self, event_id: int, player_id: int) -> Optional[Dict]:
        """Get per-match stats for a specific player in a specific event."""
        data = await self._get(f"/event/{event_id}/player/{player_id}/statistics")
        if not data:
            return None
        return data.get("statistics", {})

    async def get_cup_match_stats(
        self, player_id: int, tournament_ids: set[int], max_matches: int = 20,
    ) -> List[Dict]:
        """
        Get per-match stats for cup/european matches.
        Returns list of {tournament, round, opponent, score, stats}.
        """
        all_events = []
        for page in range(3):  # up to 3 pages of events
            events = await self.get_player_events(player_id, page)
            if not events:
                break
            all_events.extend(events)

        # Filter to requested tournaments
        cup_events = [
            e for e in all_events
            if e.get("tournament", {}).get("uniqueTournament", {}).get("id") in tournament_ids
        ]

        results = []
        for e in cup_events[:max_matches]:
            event_id = e["id"]
            tournament = e.get("tournament", {}).get("uniqueTournament", {}).get("name", "?")
            round_info = e.get("roundInfo", {})
            round_name = round_info.get("name", round_info.get("round", "?"))
            home = e.get("homeTeam", {}).get("name", "?")
            away = e.get("awayTeam", {}).get("name", "?")
            h_score = e.get("homeScore", {}).get("current", "?")
            a_score = e.get("awayScore", {}).get("current", "?")

            # Determine if this is a knockout/final stage
            stage = ""
            rn = str(round_name).lower()
            if any(k in rn for k in ["final", "финал"]):
                stage = "ФИНАЛ"
            elif any(k in rn for k in ["semi", "полуфинал"]):
                stage = "ПОЛУФИНАЛ"
            elif any(k in rn for k in ["quarter", "четвертьфинал"]):
                stage = "ЧЕТВЕРТЬФИНАЛ"
            elif any(k in rn for k in ["round of 16", "1/8"]):
                stage = "1/8 ФИНАЛА"
            elif "knockout" in rn:
                stage = "ПЛЕЙ-ОФФ"

            # Fetch per-match stats
            stats = await self.get_player_event_stats(event_id, player_id)

            results.append({
                "tournament": tournament,
                "round": str(round_name),
                "stage": stage,
                "home": home,
                "away": away,
                "score": f"{h_score}-{a_score}",
                "stats": stats or {},
            })

        return results


# ── Cup/European tournament IDs ────────────────────────────────
CUP_TOURNAMENT_IDS = {
    # European
    7,    # Champions League
    679,  # Europa League
    17015,  # Conference League
    # Domestic cups
    19,   # FA Cup
    21,   # EFL Cup / Carabao
    329,  # Copa del Rey
    217,  # DFB Pokal
    328,  # Coppa Italia
    335,  # Coupe de France
}


def format_cup_matches(matches: List[Dict]) -> str:
    """Format cup/european match stats for AI analysis."""
    if not matches:
        return ""

    lines = ["*Кубки и еврокубки (поматчево, SofaScore):*"]

    for m in matches:
        stage_tag = f" [{m['stage']}]" if m["stage"] else ""
        s = m["stats"]
        mins = s.get("minutesPlayed", 0)
        rating = s.get("rating", "—")
        goals = s.get("goals", 0) or 0
        assists = s.get("goalAssist", 0) or 0
        xg = s.get("expectedGoals")
        xa = s.get("expectedAssists")
        tackles = s.get("tackles", 0) or 0
        dribbles = s.get("successfulDribbles", 0) or 0
        duels_won = s.get("duelWon", 0) or 0
        passes = s.get("accuratePass", 0) or 0
        total_pass = s.get("totalPass", 0) or 0

        xg_str = f"xG {xg:.2f}" if xg else ""
        xa_str = f"xA {xa:.2f}" if xa else ""
        xg_xa = f" | {xg_str} {xa_str}".strip(" |") if (xg_str or xa_str) else ""

        lines.append(
            f"  {m['tournament']} R{m['round']}{stage_tag}: "
            f"{m['home']} {m['score']} {m['away']}"
        )
        lines.append(
            f"    {mins}мин | рейтинг {rating} | {goals}г {assists}а{xg_xa} | "
            f"отб {tackles} дриб {dribbles} ед {duels_won} пас {passes}/{total_pass}"
        )

    return "\n".join(lines)


POSITION_NAMES = {
    "GK": "Вратарь", "DR": "Правый защитник", "DL": "Левый защитник",
    "DC": "Центральный защитник", "DM": "Опорный полузащитник",
    "MC": "Центральный полузащитник", "MR": "Правый полузащитник",
    "ML": "Левый полузащитник", "AM": "Атакующий полузащитник",
    "AMR": "Правый вингер", "AML": "Левый вингер",
    "FW": "Нападающий", "F": "Нападающий", "FC": "Центрфорвард",
    "M": "Полузащитник", "D": "Защитник",
}


def format_sofascore_extra(stats: Dict) -> str:
    """Format SofaScore stats into detailed blocks for AI analysis."""
    if not stats:
        return ""

    lines = []

    # === Positions ===
    positions = stats.get("_positions_detailed", [])
    if positions:
        pos_names = [POSITION_NAMES.get(p, p) for p in positions]
        lines.append(f"*Позиции в этом сезоне (SofaScore):* {', '.join(pos_names)}")
        lines.append(f"  Коды позиций: {', '.join(positions)}")
        if len(positions) > 1:
            lines.append(f"  Основная: {pos_names[0]} | Также играл: {', '.join(pos_names[1:])}")
        lines.append("")

    # === Defensive stats ===
    has_def = False
    def_lines = ["*Оборонительные действия (SofaScore):*"]

    tackles = stats.get("tackles")
    tackles_won = stats.get("tacklesWon")
    tackles_pct = stats.get("tacklesWonPercentage")
    if tackles is not None:
        s = f"  Отборы: {tackles} (выиграно {tackles_won}"
        if tackles_pct is not None:
            s += f", {tackles_pct:.1f}%"
        s += ")"
        def_lines.append(s)
        has_def = True

    interceptions = stats.get("interceptions")
    if interceptions is not None:
        def_lines.append(f"  Перехваты: {interceptions}")
        has_def = True

    clearances = stats.get("clearances")
    if clearances is not None:
        def_lines.append(f"  Выносы: {clearances}")
        has_def = True

    blocks = stats.get("outfielderBlocks")
    blocked_shots = stats.get("blockedShots")
    if blocks is not None or blocked_shots is not None:
        def_lines.append(f"  Блоки: {blocks or 0} | Заблокированные удары: {blocked_shots or 0}")
        has_def = True

    recovery = stats.get("ballRecovery")
    if recovery is not None:
        def_lines.append(f"  Возвраты мяча: {recovery}")
        has_def = True

    fouls = stats.get("fouls")
    was_fouled = stats.get("wasFouled")
    if fouls is not None:
        def_lines.append(f"  Фолы совершены: {fouls} | Заработаны: {was_fouled or 0}")
        has_def = True

    if has_def:
        lines.extend(def_lines)
        lines.append("")

    # === Dribbling ===
    drib_lines = ["*Дриблинг (SofaScore):*"]
    has_drib = False

    succ = stats.get("successfulDribbles")
    total = stats.get("totalContest")
    pct = stats.get("successfulDribblesPercentage")
    if succ is not None and total is not None:
        s = f"  Обводки: {succ}/{total} успешных"
        if pct is not None:
            s += f" ({pct:.1f}%)"
        drib_lines.append(s)
        has_drib = True

    disp = stats.get("dispossessed")
    if disp is not None:
        drib_lines.append(f"  Потери при обводке: {disp}")
        has_drib = True

    poss_lost = stats.get("possessionLost")
    if poss_lost is not None:
        drib_lines.append(f"  Всего потерь владения: {poss_lost}")
        has_drib = True

    if has_drib:
        lines.extend(drib_lines)
        lines.append("")

    # === Duels ===
    duel_lines = ["*Единоборства (SofaScore):*"]
    has_duel = False

    total_duels = stats.get("totalDuelsWon")
    total_duels_pct = stats.get("totalDuelsWonPercentage")
    if total_duels is not None:
        s = f"  Всего выиграно: {total_duels}"
        if total_duels_pct is not None:
            s += f" ({total_duels_pct:.1f}%)"
        duel_lines.append(s)
        has_duel = True

    ground_won = stats.get("groundDuelsWon")
    ground_pct = stats.get("groundDuelsWonPercentage")
    if ground_won is not None:
        s = f"  Наземные: {ground_won} выиграно"
        if ground_pct is not None:
            s += f" ({ground_pct:.1f}%)"
        duel_lines.append(s)
        has_duel = True

    aerial_won = stats.get("aerialDuelsWon")
    aerial_pct = stats.get("aerialDuelsWonPercentage")
    if aerial_won is not None:
        s = f"  Воздушные: {aerial_won} выиграно"
        if aerial_pct is not None:
            s += f" ({aerial_pct:.1f}%)"
        duel_lines.append(s)
        has_duel = True

    if has_duel:
        lines.extend(duel_lines)
        lines.append("")

    # === Attacking extras ===
    att_lines = ["*Атакующие детали (SofaScore):*"]
    has_att = False

    poss_won = stats.get("possessionWonAttThird")
    if poss_won is not None:
        att_lines.append(f"  Отборы в атакующей трети: {poss_won}")
        has_att = True

    bc_created = stats.get("bigChancesCreated")
    bc_missed = stats.get("bigChancesMissed")
    if bc_created is not None or bc_missed is not None:
        parts = []
        if bc_created is not None:
            parts.append(f"создано {bc_created}")
        if bc_missed is not None:
            parts.append(f"упущено {bc_missed}")
        att_lines.append(f"  Голевые моменты: {', '.join(parts)}")
        has_att = True

    touches = stats.get("touches")
    if touches:
        att_lines.append(f"  Касания: {touches}")
        has_att = True

    shots_in = stats.get("shotsFromInsideTheBox")
    shots_out = stats.get("shotsFromOutsideTheBox")
    if shots_in is not None or shots_out is not None:
        att_lines.append(f"  Удары из штрафной: {shots_in or 0} | Из-за штрафной: {shots_out or 0}")
        has_att = True

    goals_in = stats.get("goalsFromInsideTheBox")
    goals_out = stats.get("goalsFromOutsideTheBox")
    if goals_in is not None:
        att_lines.append(f"  Голы из штрафной: {goals_in} | Издалека: {goals_out or 0}")
        has_att = True

    if has_att:
        lines.extend(att_lines)
        lines.append("")

    # === Passing ===
    pass_lines = ["*Пасы (SofaScore):*"]
    has_pass = False

    acc_passes = stats.get("accuratePasses")
    total_passes = stats.get("totalPasses")
    acc_pct = stats.get("accuratePassesPercentage")
    if acc_passes is not None and total_passes is not None:
        s = f"  Точные пасы: {acc_passes}/{total_passes}"
        if acc_pct is not None:
            s += f" ({acc_pct:.1f}%)"
        pass_lines.append(s)
        has_pass = True

    acc_long = stats.get("accurateLongBalls")
    total_long = stats.get("totalLongBalls")
    long_pct = stats.get("accurateLongBallsPercentage")
    if acc_long is not None and total_long is not None:
        s = f"  Длинные передачи: {acc_long}/{total_long}"
        if long_pct is not None:
            s += f" ({long_pct:.1f}%)"
        pass_lines.append(s)
        has_pass = True

    acc_cross = stats.get("accurateCrosses")
    total_cross = stats.get("totalCross")
    if acc_cross is not None and total_cross is not None:
        pass_lines.append(f"  Кроссы: {acc_cross}/{total_cross} точных")
        has_pass = True

    acc_ft = stats.get("accurateFinalThirdPasses")
    if acc_ft is not None:
        pass_lines.append(f"  Точные пасы в финальную треть: {acc_ft}")
        has_pass = True

    opp_half = stats.get("accurateOppositionHalfPasses")
    own_half = stats.get("accurateOwnHalfPasses")
    if opp_half is not None and own_half is not None:
        pass_lines.append(f"  Пасы на чужой половине: {opp_half} | На своей: {own_half}")
        has_pass = True

    key_passes = stats.get("keyPasses")
    if key_passes is not None:
        pass_lines.append(f"  Ключевые передачи: {key_passes}")
        has_pass = True

    if has_pass:
        lines.extend(pass_lines)
        lines.append("")

    # === Extra details ===
    extra_lines = ["*Прочее (SofaScore):*"]
    has_extra = False

    offsides = stats.get("offsides")
    if offsides is not None and offsides > 0:
        extra_lines.append(f"  Офсайды: {offsides}")
        has_extra = True

    woodwork = stats.get("hitWoodwork")
    if woodwork is not None and woodwork > 0:
        extra_lines.append(f"  Попадания в штангу/перекладину: {woodwork}")
        has_extra = True

    errors_goal = stats.get("errorLeadToGoal")
    errors_shot = stats.get("errorLeadToShot")
    if (errors_goal and errors_goal > 0) or (errors_shot and errors_shot > 0):
        extra_lines.append(f"  Ошибки → гол: {errors_goal or 0} | Ошибки → удар: {errors_shot or 0}")
        has_extra = True

    scoring_freq = stats.get("scoringFrequency")
    if scoring_freq is not None and scoring_freq > 0:
        extra_lines.append(f"  Частота голов: каждые {scoring_freq} минут")
        has_extra = True

    penalty_won = stats.get("penaltyWon")
    if penalty_won is not None and penalty_won > 0:
        extra_lines.append(f"  Заработано пенальти: {penalty_won}")
        has_extra = True

    # Goalkeeper stats
    saves = stats.get("saves")
    if saves is not None and saves > 0:
        saves_caught = stats.get("savesCaught") or 0
        saves_parried = stats.get("savesParried") or 0
        goals_conceded = stats.get("goalsConceded") or 0
        clean_sheets = stats.get("cleanSheet") or 0
        penalty_save = stats.get("penaltySave") or 0
        extra_lines.append(f"  Сейвы: {saves} (поймано {saves_caught}, отбито {saves_parried})")
        extra_lines.append(f"  Пропущено: {goals_conceded} | Сухие матчи: {clean_sheets}")
        if penalty_save > 0:
            extra_lines.append(f"  Отбито пенальти: {penalty_save}")
        has_extra = True

    if has_extra:
        lines.extend(extra_lines)

    if not lines:
        return ""
    return "\n".join(lines)
