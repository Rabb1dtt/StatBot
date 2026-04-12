"""Player-related tools for the orchestrator."""

import logging
from datetime import datetime, timezone
from typing import Any

from stats_formatter import format_player_stats, format_match_breakdown
from sofascore_client import format_sofascore_extra, format_cup_matches, CUP_TOURNAMENT_IDS

logger = logging.getLogger(__name__)


async def resolve_player(player_name: str, clients: dict[str, Any], team_hint: str = "") -> str:
    """Resolve a player name to ID, team, league, position."""
    resolver = clients["resolver"]
    resolved = await resolver.resolve(player_name, team_hint=team_hint or None)
    if not resolved:
        return f"Player '{player_name}' not found. Available leagues: EPL, La Liga, Serie A, Bundesliga, Ligue 1, RPL."
    return (
        f"Name: {resolved.name}\n"
        f"Team: {resolved.team}\n"
        f"League: {resolved.league}\n"
        f"Position: {resolved.position}\n"
        f"Understat ID: {resolved.understat_id}"
    )


async def get_player_stats(
    player_name: str,
    clients: dict[str, Any],
    team_hint: str = "",
    season_year: str = "",
) -> str:
    """Fetch full season stats for a player: Understat + SofaScore + cup + standings + web context."""
    resolver = clients["resolver"]
    usc = clients["usc"]
    sofa = clients["sofa"]

    resolved = await resolver.resolve(player_name, team_hint=team_hint or None)
    if not resolved:
        return f"Player '{player_name}' not found. Available leagues: EPL, La Liga, Serie A, Bundesliga, Ligue 1, RPL."

    target_season = season_year or "2025"
    season = await usc.get_current_season(resolved.understat_id, season=target_season)
    if not season:
        return f"No stats for season {target_season}/{int(target_season)+1} for {resolved.name}."

    text = format_player_stats(
        name=resolved.name,
        team=resolved.team,
        league=resolved.league,
        position=resolved.position,
        stats=season,
    )

    # Per-opponent breakdown
    try:
        matches = await usc.get_match_stats(resolved.understat_id)
        breakdown = format_match_breakdown(resolved.team, matches, season.get("season", "2025"))
        if breakdown:
            text += "\n\n" + breakdown
    except Exception:
        logger.exception("match breakdown failed")

    # SofaScore dribbling/duels
    try:
        sofa_stats = await sofa.get_player_stats(resolved.name, resolved.league, season_year=season_year or None)
        extra = format_sofascore_extra(sofa_stats) if sofa_stats else ""
        if extra:
            text += "\n\n" + extra
    except Exception:
        logger.exception("sofascore fetch failed")

    # Cup/european match stats
    try:
        sofa_player = await sofa.search_player(resolved.name)
        if sofa_player:
            date_from = f"{season_year}-08-01" if season_year else None
            date_to = f"{int(season_year)+1}-06-30" if season_year and season_year != "2025" else None
            max_pages = 15 if season_year and season_year != "2025" else 10
            cup_matches = await sofa.get_cup_match_stats(
                sofa_player["id"], CUP_TOURNAMENT_IDS,
                date_from=date_from, date_to=date_to, max_pages=max_pages,
            )
            cup_text = format_cup_matches(cup_matches)
            if cup_text:
                text += "\n\n" + cup_text
    except Exception:
        logger.exception("cup stats fetch failed")

    # League standings
    try:
        standings = await sofa.get_league_top10(resolved.league, season_year=season_year or None)
        if standings:
            text += "\n\n" + standings
    except Exception:
        logger.exception("standings fetch failed")

    return text


async def get_match_breakdown(
    player_name: str,
    clients: dict[str, Any],
    team_hint: str = "",
    opponent: str = "",
    tournament: str = "",
    count: int = 0,
    all_time: bool = False,
) -> str:
    """Get per-match stats for a player from SofaScore with filters."""
    resolver = clients["resolver"]
    sofa = clients["sofa"]

    resolved = await resolver.resolve(player_name, team_hint=team_hint or None)
    if not resolved:
        return f"Player '{player_name}' not found."

    sofa_player = await sofa.search_player(resolved.name)
    if not sofa_player:
        return f"Player '{resolved.name}' not found on SofaScore."

    player_id = sofa_player["id"]
    max_pages = 15 if all_time else 3

    # Fetch events
    all_events = []
    for page in range(max_pages):
        events = await sofa.get_player_events(player_id, page)
        if not events:
            break
        all_events.extend(events)

    all_events.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)

    if not all_events:
        return "No matches found."

    # Filter
    opp_lower = opponent.lower() if opponent else None
    tourney_lower = tournament.lower() if tournament else None

    target_events = []
    for e in all_events:
        home = e.get("homeTeam", {}).get("name", "")
        away = e.get("awayTeam", {}).get("name", "")
        tourney_name = e.get("tournament", {}).get("uniqueTournament", {}).get("name", "")

        if opp_lower and opp_lower not in home.lower() and opp_lower not in away.lower():
            continue
        if tourney_lower and tourney_lower not in tourney_name.lower():
            continue

        target_events.append(e)

    if not target_events and not opponent:
        target_events = [all_events[0]]

    if count and count > 0:
        target_events = target_events[:count]

    if not target_events:
        desc = opponent or "?"
        if tournament:
            desc += f" in {tournament}"
        return f"No matches found for {resolved.name} vs '{desc}'."

    # Sort chronologically for display
    if len(target_events) > 1:
        target_events.sort(key=lambda e: e.get("startTimestamp", 0))

    stat_labels = {
        "goals": "Goals", "goalAssist": "Assists",
        "expectedGoals": "xG", "expectedAssists": "xA",
        "totalShots": "Shots", "shotsOnTarget": "On target",
        "accuratePass": "Accurate passes", "totalPass": "Total passes",
        "accurateLongBalls": "Accurate long balls", "totalLongBalls": "Long balls",
        "accurateCross": "Accurate crosses", "totalCross": "Crosses",
        "keyPass": "Key passes",
        "tackles": "Tackles", "interceptions": "Interceptions",
        "totalClearance": "Clearances", "ballRecovery": "Ball recoveries",
        "duelWon": "Duels won", "duelLost": "Duels lost",
        "aerialWon": "Aerials won", "aerialLost": "Aerials lost",
        "successfulDribbles": "Successful dribbles", "dribbleAttempts": "Dribble attempts",
        "touches": "Touches",
        "fouls": "Fouls", "wasFouled": "Was fouled",
        "saves": "Saves", "goalsPrevented": "Goals prevented",
    }

    lines = [f"Player: {resolved.name} ({resolved.team})"]
    if len(target_events) > 1:
        lines.append(f"Matches found: {len(target_events)} (chronological order)")
    lines.append("")

    for ev in target_events:
        event_id = ev["id"]
        home = ev.get("homeTeam", {}).get("name", "?")
        away = ev.get("awayTeam", {}).get("name", "?")
        h_score = ev.get("homeScore", {}).get("current", "?")
        a_score = ev.get("awayScore", {}).get("current", "?")
        tourney = ev.get("tournament", {}).get("uniqueTournament", {}).get("name", "?")
        round_info = ev.get("roundInfo", {})
        round_name = round_info.get("name", round_info.get("round", "?"))

        ts = ev.get("startTimestamp", 0)
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y") if ts else "?"

        stats = await sofa.get_player_event_stats(event_id, player_id)
        if not stats:
            lines.append(f"*{home} {h_score}-{a_score} {away}* ({date_str}, {tourney} R{round_name}) — no data")
            lines.append("")
            continue

        mins = stats.get("minutesPlayed", 0)
        rating = stats.get("rating", "—")

        lines.append(f"*{home} {h_score}-{a_score} {away}*")
        lines.append(f"Date: {date_str} | Tournament: {tourney}, round {round_name}")
        lines.append(f"Minutes: {mins} | Rating: {rating}")

        for key, label in stat_labels.items():
            val = stats.get(key)
            if val is not None and val != 0:
                if isinstance(val, float):
                    lines.append(f"  {label}: {val:.2f}")
                else:
                    lines.append(f"  {label}: {val}")
        lines.append("")

    return "\n".join(lines)
