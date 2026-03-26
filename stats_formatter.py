from typing import Dict, List, Optional


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}" if not value.is_integer() else str(int(value))
    return str(value)


def _per90(total, minutes: Optional[int]) -> Optional[float]:
    if total is None or minutes is None or minutes <= 0:
        return None
    return float(total) * 90.0 / minutes


def format_player_stats(player_data: Dict) -> str:
    """Format API-Football player response into a readable text block."""
    player = player_data.get("player", {})
    statistics = player_data.get("statistics", [])

    name = player.get("name", "Unknown")
    firstname = player.get("firstname", "")
    lastname = player.get("lastname", "")
    full_name = f"{firstname} {lastname}".strip() or name
    age = player.get("age")
    nationality = player.get("nationality")
    height = player.get("height")

    lines: List[str] = []
    lines.append(f"*{full_name}*")
    info_parts = []
    if age:
        info_parts.append(f"{age} лет")
    if nationality:
        info_parts.append(nationality)
    if height:
        info_parts.append(f"{height} см")
    if info_parts:
        lines.append(" | ".join(info_parts))
    lines.append("")

    total_apps = 0
    total_goals = 0
    total_assists = 0
    total_minutes = 0
    all_ratings: List[float] = []

    for stat in statistics:
        team = stat.get("team", {})
        league = stat.get("league", {})
        games = stat.get("games", {})

        team_name = team.get("name", "—")
        league_name = league.get("name", "—")
        country = league.get("country", "")
        season = league.get("season", "")

        apps = games.get("appearences") or 0
        minutes = games.get("minutes") or 0
        position = games.get("position", "")
        rating = games.get("rating")

        goals_data = stat.get("goals", {})
        goals = goals_data.get("total") or 0
        assists = goals_data.get("assists") or 0

        total_apps += apps
        total_goals += goals
        total_assists += assists
        total_minutes += minutes
        if rating:
            try:
                all_ratings.append(float(rating))
            except (ValueError, TypeError):
                pass

        rating_str = f"{float(rating):.2f}" if rating else "—"
        lines.append(f"*{league_name}* ({country}, {season}) — {team_name}")
        lines.append(f"  Позиция: {position}")
        lines.append(f"  Матчи: {apps} | Минуты: {minutes} | Рейтинг: {rating_str}")
        lines.append(f"  Голы: {goals} | Ассисты: {assists}")

        # Detailed stats
        detail_lines = _format_detailed(stat, minutes)
        if detail_lines:
            lines.append(detail_lines)
        lines.append("")

    # Totals
    avg_rating = f"{sum(all_ratings) / len(all_ratings):.2f}" if all_ratings else "—"
    lines.append(f"*Итого:* {total_apps} матчей, {total_goals} гол(ов), {total_assists} ассист(ов)")
    lines.append(f"Минут: {total_minutes} | Средний рейтинг: {avg_rating}")

    return "\n".join(lines)


def _format_detailed(stat: Dict, minutes: int) -> str:
    """Format shots, passes, tackles, etc."""
    parts: List[str] = []

    shots = stat.get("shots", {})
    if shots.get("total"):
        on = shots.get("on") or 0
        parts.append(f"Удары: {shots['total']} (в створ: {on})")

    passes = stat.get("passes", {})
    if passes.get("total"):
        key = passes.get("key") or 0
        acc = passes.get("accuracy")
        acc_str = f", точность {acc}%" if acc else ""
        parts.append(f"Пасы: {passes['total']} (ключевые: {key}{acc_str})")

    tackles = stat.get("tackles", {})
    if tackles.get("total"):
        interc = tackles.get("interceptions") or 0
        blocks = tackles.get("blocks") or 0
        parts.append(f"Отборы: {tackles['total']} | Перехваты: {interc} | Блоки: {blocks}")

    dribbles = stat.get("dribbles", {})
    if dribbles.get("attempts"):
        success = dribbles.get("success") or 0
        parts.append(f"Дриблинг: {success}/{dribbles['attempts']}")

    duels = stat.get("duels", {})
    if duels.get("total"):
        won = duels.get("won") or 0
        parts.append(f"Единоборства: {won}/{duels['total']}")

    fouls = stat.get("fouls", {})
    if fouls.get("committed"):
        parts.append(f"Фолы: {fouls['committed']}")

    cards = stat.get("cards", {})
    yellow = cards.get("yellow") or 0
    red = cards.get("red") or 0
    if yellow or red:
        parts.append(f"Карточки: {yellow}Ж / {red}К")

    # Per 90 for key metrics
    if minutes and minutes >= 90:
        goals = (stat.get("goals", {}).get("total") or 0)
        assists = (stat.get("goals", {}).get("assists") or 0)
        per90_parts = []
        g90 = _per90(goals, minutes)
        a90 = _per90(assists, minutes)
        if g90 is not None:
            per90_parts.append(f"Голы/90: {g90:.2f}")
        if a90 is not None:
            per90_parts.append(f"Ассисты/90: {a90:.2f}")
        shots_total = (stat.get("shots", {}).get("total") or 0)
        s90 = _per90(shots_total, minutes)
        if s90 is not None and shots_total > 0:
            per90_parts.append(f"Удары/90: {s90:.2f}")
        if per90_parts:
            parts.append("Per 90: " + " | ".join(per90_parts))

    if not parts:
        return ""
    return "  " + "\n  ".join(parts)
