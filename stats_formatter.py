from typing import Dict, List, Optional


def _fmt(value, decimals: int = 2) -> str:
    if value is None:
        return "—"
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
        return f"{f:.{decimals}f}"
    except (ValueError, TypeError):
        return str(value)


def _per90(total, minutes) -> Optional[float]:
    try:
        t = float(total)
        m = float(minutes)
    except (ValueError, TypeError):
        return None
    if m <= 0:
        return None
    return t * 90.0 / m


def format_player_stats(name: str, team: str, league: str, position: str, stats: Dict) -> str:
    """Format Understat season stats into readable text."""
    minutes = stats.get("time", 0)
    games = stats.get("games", 0)
    season = stats.get("season", "?")

    lines: List[str] = []

    header = f"*{name}*"
    if team:
        header += f" ({team})"
    if position:
        header += f" — {position}"
    lines.append(header)
    lines.append(f"Сезон {season}/{int(season)+1} | {league}")
    lines.append(f"Матчей: {games} | Минут: {minutes}")
    lines.append("")

    # Goals & assists
    goals = stats.get("goals", 0)
    assists = stats.get("assists", 0)
    npg = stats.get("npg", 0)
    lines.append(f"*Голы и ассисты:*")
    lines.append(f"  Голы: {goals} (без пенальти: {npg})")
    lines.append(f"  Ассисты: {assists}")
    g90 = _per90(goals, minutes)
    a90 = _per90(assists, minutes)
    if g90 is not None:
        lines.append(f"  Голы/90: {_fmt(g90)} | Ассисты/90: {_fmt(a90)}")
    lines.append("")

    # xG metrics
    xg = stats.get("xG")
    xa = stats.get("xA")
    npxg = stats.get("npxG")
    xg_chain = stats.get("xGChain")
    xg_buildup = stats.get("xGBuildup")

    lines.append("*Expected метрики:*")
    lines.append(f"  xG: {_fmt(xg)} | xA: {_fmt(xa)}")
    lines.append(f"  npxG: {_fmt(npxg)}")
    xg90 = _per90(xg, minutes)
    xa90 = _per90(xa, minutes)
    if xg90 is not None:
        lines.append(f"  xG/90: {_fmt(xg90)} | xA/90: {_fmt(xa90)}")

    # Over/underperformance
    try:
        g_minus_xg = int(goals) - float(xg)
        a_minus_xa = int(assists) - float(xa)
        lines.append(f"  Голы−xG: {_fmt(g_minus_xg)} | Ассисты−xA: {_fmt(a_minus_xa)}")
    except (ValueError, TypeError):
        pass

    if xg_chain:
        lines.append(f"  xGChain: {_fmt(xg_chain)} | xGBuildup: {_fmt(xg_buildup)}")
    lines.append("")

    # Shots & key passes
    shots = stats.get("shots", 0)
    key_passes = stats.get("key_passes", 0)
    lines.append("*Удары и пасы:*")
    lines.append(f"  Удары: {shots} | Ключевые пасы: {key_passes}")
    s90 = _per90(shots, minutes)
    kp90 = _per90(key_passes, minutes)
    if s90 is not None:
        lines.append(f"  Удары/90: {_fmt(s90)} | Ключевые пасы/90: {_fmt(kp90)}")

    # xG per shot
    try:
        if int(shots) > 0:
            xg_per_shot = float(xg) / int(shots)
            lines.append(f"  xG/удар: {_fmt(xg_per_shot, 3)}")
    except (ValueError, TypeError, ZeroDivisionError):
        pass
    lines.append("")

    # Cards
    yellow = stats.get("yellow_cards", 0)
    red = stats.get("red_cards", 0)
    if int(yellow) > 0 or int(red) > 0:
        lines.append(f"*Дисциплина:* ЖК: {yellow} | КК: {red}")

    return "\n".join(lines)


def format_match_breakdown(team: str, matches: List[Dict], season: str = "2025") -> str:
    """Format per-opponent breakdown from match data for AI analysis."""
    # Filter to current season
    season_matches = [m for m in matches if str(m.get("season")) == season]
    if not season_matches:
        return ""

    # Aggregate per opponent
    opponents: Dict[str, Dict] = {}
    for m in season_matches:
        h_team = m.get("h_team", "")
        a_team = m.get("a_team", "")
        opponent = a_team if h_team == team else h_team
        is_home = h_team == team

        if opponent not in opponents:
            opponents[opponent] = {
                "matches": 0, "goals": 0, "assists": 0,
                "xG": 0.0, "xA": 0.0, "shots": 0, "minutes": 0,
                "key_passes": 0, "wins": 0, "draws": 0, "losses": 0,
            }
        o = opponents[opponent]
        o["matches"] += 1
        o["goals"] += int(m.get("goals", 0))
        o["assists"] += int(m.get("assists", 0))
        o["shots"] += int(m.get("shots", 0))
        o["minutes"] += int(m.get("time", 0))
        o["key_passes"] += int(m.get("key_passes", 0))
        try:
            o["xG"] += float(m.get("xG", 0))
            o["xA"] += float(m.get("xA", 0))
        except (ValueError, TypeError):
            pass

        h_goals = int(m.get("h_goals", 0))
        a_goals = int(m.get("a_goals", 0))
        if is_home:
            team_goals, opp_goals = h_goals, a_goals
        else:
            team_goals, opp_goals = a_goals, h_goals
        if team_goals > opp_goals:
            o["wins"] += 1
        elif team_goals == opp_goals:
            o["draws"] += 1
        else:
            o["losses"] += 1

    # Sort by opponent goals+assists (productive matches first)
    sorted_opps = sorted(
        opponents.items(),
        key=lambda x: x[1]["goals"] + x[1]["assists"],
        reverse=True,
    )

    lines: List[str] = []
    lines.append("*Разбивка по соперникам (текущий сезон, только лига):*")
    lines.append("Соперник | Матчи | Голы | Ассисты | xG | xA | Удары | Результат")

    productive_goals = 0
    productive_opps = 0
    quiet_goals = 0
    quiet_opps = 0

    for opp, s in sorted_opps:
        wdl = f"{s['wins']}W-{s['draws']}D-{s['losses']}L"
        lines.append(
            f"  {opp}: {s['matches']}м | {s['goals']}г {s['assists']}а | "
            f"xG {_fmt(s['xG'])} xA {_fmt(s['xA'])} | {s['shots']}уд | {wdl}"
        )
        ga = s["goals"] + s["assists"]
        if ga > 0:
            productive_goals += s["goals"]
            productive_opps += 1
        else:
            quiet_goals += 0
            quiet_opps += 1

    # Summary for AI
    lines.append("")
    total_opps = len(opponents)
    lines.append(f"Голевые действия против {productive_opps} из {total_opps} соперников")
    lines.append(f"Без голевых действий против {quiet_opps} соперников")

    # Last 5 matches form
    recent = season_matches[:5]
    if recent:
        lines.append("")
        lines.append("*Форма (последние 5 матчей):*")
        for m in recent:
            h_team = m.get("h_team", "")
            a_team = m.get("a_team", "")
            opp = a_team if h_team == team else h_team
            venue = "Д" if h_team == team else "В"
            score = f"{m.get('h_goals')}-{m.get('a_goals')}"
            lines.append(
                f"  {m.get('date')} ({venue}) vs {opp} {score} — "
                f"{m.get('goals')}г {m.get('assists')}а, xG {_fmt(m.get('xG'))} xA {_fmt(m.get('xA'))}"
            )

    return "\n".join(lines)
