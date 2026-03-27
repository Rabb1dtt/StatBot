import asyncio
import logging
from typing import Any, Dict, List, Optional

from understatapi import UnderstatClient
from cachetools import TTLCache

logger = logging.getLogger(__name__)

CACHE_TTL = 24 * 60 * 60

# Understat league names
UNDERSTAT_LEAGUES = {
    "Premier League": "EPL",
    "LaLiga": "La_Liga",
    "La Liga": "La_Liga",
    "Serie A": "Serie_A",
    "Bundesliga": "Bundesliga",
    "Ligue 1": "Ligue_1",
    "Russian Premier League": "RFPL",
}


class TeamDataClient:
    """Fetches team-level data from Understat for coach/team analysis."""

    def __init__(self) -> None:
        self._cache: TTLCache = TTLCache(maxsize=128, ttl=CACHE_TTL)

    def _get_team_data_sync(self, league: str, season: str) -> Dict[str, Dict]:
        """Get all teams data for a league/season from Understat."""
        us_league = UNDERSTAT_LEAGUES.get(league, league)
        with UnderstatClient() as usc:
            return usc.league(league=us_league).get_team_data(season=season)

    async def get_team_season(self, team_name: str, league: str, season: str = "2025", coach_since: Optional[str] = None, coach_until: Optional[str] = None) -> Optional[Dict]:
        """Get a specific team's season data with aggregated stats."""
        cache_key = f"{league}:{season}"
        cached = self._cache.get(cache_key)
        if not cached:
            cached = await asyncio.to_thread(self._get_team_data_sync, league, season)
            self._cache[cache_key] = cached

        if not cached:
            return None

        # Find team by name (fuzzy)
        target = team_name.lower()
        for tid, tdata in cached.items():
            if target in tdata.get("title", "").lower():
                return self._aggregate(tdata, since_date=coach_since, until_date=coach_until)

        return None

    def _aggregate(self, tdata: Dict, since_date: Optional[str] = None, until_date: Optional[str] = None) -> Dict:
        """Aggregate per-match data into season summary.
        since_date: only include matches on or after this date.
        until_date: only include matches on or before this date.
        """
        history = tdata.get("history", [])
        if since_date:
            history = [m for m in history if m.get("date", "")[:10] >= since_date]
        if until_date:
            history = [m for m in history if m.get("date", "")[:10] <= until_date]
        if not history:
            return {"title": tdata.get("title"), "matches": 0}

        # Period
        dates = sorted(m.get("date", "")[:10] for m in history if m.get("date"))
        first_date = dates[0] if dates else "?"
        last_date = dates[-1] if dates else "?"

        total_xg = sum(m["xG"] for m in history)
        total_xga = sum(m["xGA"] for m in history)
        total_npxg = sum(m["npxG"] for m in history)
        total_npxga = sum(m["npxGA"] for m in history)
        total_goals = sum(m["scored"] for m in history)
        total_conceded = sum(m["missed"] for m in history)
        total_pts = sum(m["pts"] for m in history)
        wins = sum(1 for m in history if m["result"] == "w")
        draws = sum(1 for m in history if m["result"] == "d")
        losses = sum(1 for m in history if m["result"] == "l")
        matches = len(history)

        # PPDA (pressing intensity)
        ppda_values = []
        oppda_values = []
        for m in history:
            ppda = m.get("ppda", {})
            if ppda.get("def", 0) > 0:
                ppda_values.append(ppda["att"] / ppda["def"])
            oppda = m.get("ppda_allowed", {})
            if oppda.get("def", 0) > 0:
                oppda_values.append(oppda["att"] / oppda["def"])

        avg_ppda = sum(ppda_values) / len(ppda_values) if ppda_values else 0
        avg_oppda = sum(oppda_values) / len(oppda_values) if oppda_values else 0

        # Deep completions
        total_deep = sum(m.get("deep", 0) for m in history)
        total_deep_allowed = sum(m.get("deep_allowed", 0) for m in history)

        # Form (last 5)
        form = []
        for m in history[-5:]:
            form.append({
                "date": m.get("date", "")[:10],
                "h_a": m.get("h_a", ""),
                "xG": round(m["xG"], 2),
                "xGA": round(m["xGA"], 2),
                "scored": m["scored"],
                "missed": m["missed"],
                "result": m["result"],
                "ppda": round(m["ppda"]["att"] / max(m["ppda"]["def"], 1), 1),
            })

        return {
            "title": tdata.get("title"),
            "id": tdata.get("id"),
            "matches": matches,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "points": total_pts,
            "ppg": round(total_pts / max(matches, 1), 2),
            "goals": total_goals,
            "conceded": total_conceded,
            "gd": total_goals - total_conceded,
            "xG": round(total_xg, 2),
            "xGA": round(total_xga, 2),
            "xGD": round(total_xg - total_xga, 2),
            "npxG": round(total_npxg, 2),
            "npxGA": round(total_npxga, 2),
            "goals_minus_xG": round(total_goals - total_xg, 2),
            "conceded_minus_xGA": round(total_conceded - total_xga, 2),
            "ppda": round(avg_ppda, 1),
            "oppda": round(avg_oppda, 1),
            "deep": total_deep,
            "deep_allowed": total_deep_allowed,
            "deep_per_match": round(total_deep / max(matches, 1), 1),
            "form": form,
            "first_date": first_date,
            "last_date": last_date,
        }


def format_team_data(team: Dict, sofa_team_stats: Optional[Dict] = None, standings: Optional[str] = None, manager: Optional[Dict] = None, coach_name: Optional[str] = None, coach_since: Optional[str] = None, cup_results: Optional[List[Dict]] = None, coach_until: Optional[str] = None) -> str:
    """Format team data for AI analysis."""
    lines = []
    title = team.get("title", "?")
    lines.append(f"*Команда: {title}*")
    # Coach info
    mgr_display = coach_name
    if not mgr_display and manager:
        mgr_display = manager.get("name")
    if mgr_display:
        coach_line = f"Тренер: {mgr_display}"
        if manager:
            country = manager.get("country", {}).get("name", "")
            if country:
                coach_line += f" ({country})"
        lines.append(coach_line)

    # Evaluation period
    first = team.get("first_date", "?")
    last = team.get("last_date", "?")
    if coach_since and coach_until:
        lines.append(f"Период оценки: {first} — {last} (назначен {coach_since}, уволен/ушёл {coach_until})")
    elif coach_since:
        lines.append(f"Период оценки: {first} — {last} (в клубе с {coach_since})")
    else:
        lines.append(f"Период оценки: {first} — {last}")
    lines.append(f"Матчей: {team['matches']} | {team['wins']}W {team['draws']}D {team['losses']}L | {team['points']} очков (PPG: {team['ppg']})")
    lines.append(f"Голы: {team['goals']} забито, {team['conceded']} пропущено (разница: {team['gd']})")
    lines.append("")

    # xG analysis
    lines.append("*Expected Goals:*")
    lines.append(f"  xG: {team['xG']} | xGA: {team['xGA']} | xGD: {team['xGD']}")
    lines.append(f"  npxG: {team['npxG']} | npxGA: {team['npxGA']}")
    lines.append(f"  Голы − xG: {team['goals_minus_xG']} (реализация)")
    lines.append(f"  Пропущенные − xGA: {team['conceded_minus_xGA']} (надёжность)")
    lines.append("")

    # Pressing
    lines.append("*Прессинг:*")
    ppda = team["ppda"]
    if ppda < 8:
        press_label = "агрессивный"
    elif ppda < 11:
        press_label = "умеренный"
    else:
        press_label = "низкий"
    lines.append(f"  PPDA: {ppda} ({press_label})")
    lines.append(f"  OPPDA: {team['oppda']} (выход из-под чужого прессинга)")
    lines.append("")

    # Deep completions
    lines.append("*Проникновения в штрафную:*")
    lines.append(f"  Deep completions: {team['deep']} ({team['deep_per_match']}/матч)")
    lines.append(f"  Deep allowed: {team['deep_allowed']}")
    lines.append("")

    # SofaScore team stats
    if sofa_team_stats:
        lines.append("*Детали (SofaScore):*")
        s = sofa_team_stats
        possession = s.get("averageBallPossession")
        if possession:
            lines.append(f"  Среднее владение: {possession:.1f}%")

        acc_pass = s.get("accuratePassesPercentage")
        if acc_pass:
            lines.append(f"  Точность пасов: {acc_pass:.1f}%")

        crosses = s.get("accurateCrosses")
        total_crosses = s.get("totalCrosses")
        if crosses is not None and total_crosses:
            lines.append(f"  Кроссы: {crosses}/{total_crosses} точных")

        long_balls = s.get("accurateLongBalls")
        total_long = s.get("totalLongBalls")
        if long_balls is not None and total_long:
            lines.append(f"  Длинные передачи: {long_balls}/{total_long}")

        big_chances = s.get("bigChancesCreated")
        big_against = s.get("bigChancesCreatedAgainst")
        if big_chances is not None:
            lines.append(f"  Big chances: создано {big_chances}, допущено {big_against or '?'}")

        errors = s.get("errorsLeadingToGoal")
        errors_ag = s.get("errorsLeadingToGoalAgainst")
        if errors is not None:
            lines.append(f"  Ошибки → гол: свои {errors}, соперника {errors_ag or '?'}")

        clean = s.get("cleanSheets")
        if clean is not None:
            lines.append(f"  Сухие матчи: {clean}")

        yellow = s.get("yellowCards")
        red = s.get("redCards")
        if yellow is not None:
            lines.append(f"  Карточки: {yellow} ЖК, {red or 0} КК")

        corners = s.get("corners")
        if corners is not None:
            lines.append(f"  Угловые: {corners}")

        opp_half = s.get("accurateOppositionHalfPasses")
        own_half = s.get("accurateOwnHalfPasses")
        if opp_half and own_half:
            total = opp_half + own_half
            territory = round(opp_half / total * 100, 1)
            lines.append(f"  Территория (пасы на чужой половине): {territory}%")

        shots = s.get("shots")
        shots_ag = s.get("shotsAgainst")
        if shots:
            lines.append(f"  Удары: {shots} нанесено, {shots_ag or '?'} допущено")

        lines.append("")

    # Form
    form = team.get("form", [])
    if form:
        lines.append("*Форма (последние 5 матчей):*")
        for m in form:
            venue = "Д" if m["h_a"] == "h" else "В"
            res = {"w": "П", "d": "Н", "l": "Пр"}.get(m["result"], "?")
            lines.append(
                f"  {m['date']} ({venue}) {m['scored']}-{m['missed']} [{res}] "
                f"xG {m['xG']} xGA {m['xGA']} PPDA {m['ppda']}"
            )
        lines.append("")

    # Cup/European results
    if cup_results:
        lines.append("*Кубки и еврокубки:*")
        # Group by tournament
        by_tourney: Dict[str, List] = {}
        for m in cup_results:
            t = m.get("tournament", "?")
            by_tourney.setdefault(t, []).append(m)

        for tourney, matches in by_tourney.items():
            wins = sum(1 for m in matches if m.get("result") == "w")
            draws = sum(1 for m in matches if m.get("result") == "d")
            losses = sum(1 for m in matches if m.get("result") == "l")
            gf = sum(m.get("goals_for", 0) for m in matches)
            ga = sum(m.get("goals_against", 0) for m in matches)
            lines.append(f"  {tourney}: {len(matches)}м {wins}W {draws}D {losses}L ({gf}-{ga})")
            # Show knockout stages
            for m in matches:
                stage = m.get("stage", "")
                if stage:
                    lines.append(f"    {stage}: {m.get('home')} {m.get('score')} {m.get('away')}")
        lines.append("")

    # Standings
    if standings:
        lines.append(standings)

    return "\n".join(lines)
