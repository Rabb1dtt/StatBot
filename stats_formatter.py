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
