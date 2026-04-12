"""Team and coach tools for the orchestrator."""

import logging
from datetime import datetime, timezone
from typing import Any

from team_client import format_team_data, UNDERSTAT_LEAGUES
from sofascore_client import LEAGUE_TOURNAMENT_IDS

logger = logging.getLogger(__name__)


async def get_team_stats(
    team_name: str,
    league: str,
    clients: dict[str, Any],
    coach_name: str = "",
    coach_since: str = "",
    coach_until: str = "",
) -> str:
    """Fetch team season data from Understat + SofaScore. Supports coach date filtering."""
    team_client = clients["team_client"]
    sofa = clients["sofa"]
    resolver = clients["resolver"]

    us_league = UNDERSTAT_LEAGUES.get(league)
    has_understat = us_league is not None

    team_data = None
    if has_understat:
        try:
            team_data = await team_client.get_team_season(
                team_name, league,
                coach_since=coach_since or None,
                coach_until=coach_until or None,
            )
        except Exception as e:
            logger.warning("Understat failed for %s: %s", team_name, e)

    if not team_data:
        team_data = {
            "title": team_name, "matches": 0, "wins": 0, "draws": 0, "losses": 0,
            "points": 0, "ppg": 0, "goals": 0, "conceded": 0, "gd": 0,
            "xG": 0, "xGA": 0, "xGD": 0, "npxG": 0, "npxGA": 0,
            "goals_minus_xG": 0, "conceded_minus_xGA": 0,
            "ppda": 0, "oppda": 0, "deep": 0, "deep_allowed": 0, "deep_per_match": 0,
            "form": [], "first_date": "?", "last_date": "?",
        }

    # SofaScore team stats (skip if partial season — misleading for coach comparison)
    skip_sofa_stats = bool(coach_until)
    sofa_team_stats = None
    manager = None
    sofa_team_id = None

    try:
        sofa_search = await sofa._get(f"/search/teams?q={team_name}")
        if sofa_search:
            sofa_teams = sofa_search.get("results", [])
            if sofa_teams:
                sofa_team_id = sofa_teams[0].get("entity", {}).get("id")
                if sofa_team_id:
                    team_info = await sofa._get(f"/team/{sofa_team_id}")
                    if team_info:
                        manager = team_info.get("team", {}).get("manager")

                    if not skip_sofa_stats:
                        us_l = UNDERSTAT_LEAGUES.get(league, league)
                        ut_id = LEAGUE_TOURNAMENT_IDS.get(us_l)
                        if ut_id:
                            season_id = await sofa._get_current_season(ut_id)
                            if season_id:
                                data = await sofa._get(
                                    f"/team/{sofa_team_id}/unique-tournament/{ut_id}/season/{season_id}/statistics/overall"
                                )
                                if data:
                                    sofa_team_stats = data.get("statistics", {})
    except Exception:
        logger.exception("sofa team fetch failed")

    # Auto-detect coach departure
    if coach_name and not coach_until and manager:
        current_mgr = manager.get("name", "")
        if current_mgr and current_mgr.lower() != coach_name.lower():
            logger.info("Coach mismatch: %s vs current %s, searching for departure", coach_name, current_mgr)
            try:
                info = await resolver.search_specific_coach(coach_name, team_name)
                if info and info.get("coach_until"):
                    coach_until = info["coach_until"]
                    team_data = await team_client.get_team_season(
                        team_name, league,
                        coach_since=coach_since or None,
                        coach_until=coach_until,
                    )
                    if not team_data:
                        return f"No data for period {coach_since} — {coach_until}."
            except Exception:
                logger.exception("coach departure search failed")

    # Standings
    standings = None
    try:
        us_l = UNDERSTAT_LEAGUES.get(league, league)
        standings = await sofa.get_league_top10(us_l)
    except Exception:
        pass

    # Cup/European results
    cup_results = []
    try:
        if sofa_team_id:
            if not has_understat:
                max_pages = 10
            elif coach_since and coach_since < "2024-01-01":
                max_pages = 25
            else:
                max_pages = 3
            team_events = await sofa.get_team_events(sofa_team_id, max_pages=max_pages)
            league_tid = LEAGUE_TOURNAMENT_IDS.get(us_league) if us_league else None

            for e in team_events:
                tid = e.get("tournament", {}).get("uniqueTournament", {}).get("id")
                is_league = (tid == league_tid) if league_tid else False
                if is_league and has_understat:
                    continue

                ts = e.get("startTimestamp", 0)
                match_date = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
                if match_date:
                    if coach_since and match_date < coach_since:
                        continue
                    if coach_until and match_date > coach_until:
                        continue

                home = e.get("homeTeam", {}).get("name", "?")
                away = e.get("awayTeam", {}).get("name", "?")
                hs = e.get("homeScore", {}).get("current", 0)
                aws = e.get("awayScore", {}).get("current", 0)
                tname = e.get("tournament", {}).get("uniqueTournament", {}).get("name", "?")
                rinfo = e.get("roundInfo", {})
                rname = rinfo.get("name", rinfo.get("round", ""))

                is_home = team_name.lower() in home.lower()
                gf = hs if is_home else aws
                ga = aws if is_home else hs
                if gf > ga:
                    result = "w"
                elif gf == ga:
                    result = "d"
                else:
                    result = "l"

                stage = ""
                rn = str(rname).lower()
                if any(k in rn for k in ["final"]):
                    stage = "FINAL" if "semi" not in rn else "SEMIFINAL"
                elif "semi" in rn:
                    stage = "SEMIFINAL"
                elif "quarter" in rn:
                    stage = "QUARTERFINAL"

                cup_results.append({
                    "tournament": tname,
                    "round": str(rname),
                    "stage": stage,
                    "home": home,
                    "away": away,
                    "score": f"{hs}-{aws}",
                    "_date": match_date,
                    "goals_for": gf,
                    "goals_against": ga,
                    "result": result,
                })
    except Exception:
        logger.exception("cup results fetch failed")

    if coach_until and cup_results:
        cup_results = [c for c in cup_results if not c.get("_date") or c["_date"] <= coach_until]

    # Build from SofaScore if no Understat data
    if not has_understat or team_data.get("matches", 0) == 0:
        all_sofa = cup_results
        if all_sofa:
            wins = sum(1 for m in all_sofa if m["result"] == "w")
            draws = sum(1 for m in all_sofa if m["result"] == "d")
            losses = sum(1 for m in all_sofa if m["result"] == "l")
            gf = sum(m.get("goals_for", 0) for m in all_sofa)
            ga = sum(m.get("goals_against", 0) for m in all_sofa)
            matches = len(all_sofa)
            dates = sorted(m["_date"] for m in all_sofa if m.get("_date"))
            team_data = {
                "title": team_name,
                "matches": matches,
                "wins": wins, "draws": draws, "losses": losses,
                "points": wins * 3 + draws,
                "ppg": round((wins * 3 + draws) / max(matches, 1), 2),
                "goals": gf, "conceded": ga, "gd": gf - ga,
                "xG": 0, "xGA": 0, "xGD": 0, "npxG": 0, "npxGA": 0,
                "goals_minus_xG": 0, "conceded_minus_xGA": 0,
                "ppda": 0, "oppda": 0, "deep": 0, "deep_allowed": 0, "deep_per_match": 0,
                "form": [],
                "first_date": dates[0] if dates else "?",
                "last_date": dates[-1] if dates else "?",
            }

    text = format_team_data(
        team_data, sofa_team_stats, standings, manager,
        coach_name or None, coach_since or None, cup_results, coach_until or None,
    )
    return text


async def get_coach_info(coach_name: str, clients: dict[str, Any]) -> str:
    """Search for coach information: current team, appointment date, league."""
    resolver = clients["resolver"]

    info = await resolver.search_coach_info(coach_name)
    if not info:
        return f"Could not find coach info for '{coach_name}'."

    lines = []
    if info.get("coach_name"):
        lines.append(f"Coach: {info['coach_name']}")
    if info.get("team"):
        lines.append(f"Team: {info['team']}")
    if info.get("league"):
        lines.append(f"League: {info['league']}")
    if info.get("coach_since"):
        lines.append(f"Appointed: {info['coach_since']}")
    return "\n".join(lines) if lines else f"No details found for '{coach_name}'."
