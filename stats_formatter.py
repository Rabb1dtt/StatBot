from typing import Dict, List, Optional, Tuple


def _to_int(value: Optional[str]) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _to_float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _per90(total: float, minutes: Optional[float]) -> Optional[float]:
    if minutes is None or minutes <= 0:
        return None
    return total * 90.0 / minutes


def format_tournament_stats(
    season_name: str,
    tournaments: List[Dict],
    advanced: Optional[Dict] = None,
) -> str:
    if not tournaments:
        return "Нет статистики за текущий сезон."

    lines: List[str] = []
    lines.append(f"*Сезон {season_name}*")
    lines.append("_Лига — матчи / голы / ассисты / рейтинг_")

    total_games = total_goals = total_assists = 0
    ratings: List[float] = []

    for t in tournaments:
        league = t.get("leagueName", "—")
        apps = _to_int(t.get("appearances"))
        goals = _to_int(t.get("goals"))
        assists = _to_int(t.get("assists"))
        rating_val = _to_float((t.get("rating") or {}).get("rating"))
        total_games += apps
        total_goals += goals
        total_assists += assists
        if rating_val is not None:
            ratings.append(rating_val)

        rating_str = f"{rating_val:.2f}" if rating_val is not None else "—"
        lines.append(f"{league}: {apps} / {goals} / {assists} / {rating_str}")

    avg_rating = f"{(sum(ratings) / len(ratings)):.2f}" if ratings else "—"
    lines.append("")
    lines.append(f"*Итого:* {total_games} матчей, {total_goals} гол(ов), {total_assists} ассист(ов), средняя оценка {avg_rating}")

    lines.append("")
    lines.append(_format_advanced_block(advanced))

    return "\n".join(lines)


def _format_advanced_block(advanced: Optional[Dict]) -> str:
    if not advanced or not advanced.get("metrics"):
        return "_Advanced stats unavailable_"

    minutes = advanced.get("minutes")
    is_goalkeeper = bool(advanced.get("is_goalkeeper"))
    metrics = advanced.get("metrics", {})

    lines: List[str] = []
    lines.append("*Advanced:*")
    if minutes is not None:
        lines.append(f"Minutes: {int(minutes)}")
        if minutes < 450:
            lines.append("_Small sample_")

    def add_line(label: str, key: str) -> None:
        if key not in metrics:
            return
        total = metrics[key]
        per90 = _per90(total, minutes)
        if per90 is None:
            lines.append(f"{label}: {_format_number(total)}")
        else:
            lines.append(f"{label}: {_format_number(total)} ({_format_number(per90)}/90)")

    if is_goalkeeper:
        add_line("Goals prevented", "goals_prevented")
        add_line("Saves", "saves")
        add_line("Clean sheets", "clean_sheets")
        add_line("Goals conceded", "goals_conceded")
        # show xGOT if present for GK
        add_line("xGOT", "xgot")
    else:
        add_line("xG", "xg")
        add_line("xA", "xa")
        add_line("xGOT", "xgot")
        add_line("Shots", "shots")
        add_line("Shots on target", "shots_on_target")
        add_line("Big chances created", "big_chances_created")
        add_line("Big chances missed", "big_chances_missed")
        add_line("Accurate passes", "accurate_passes")
        add_line("Tackles", "tackles")
        add_line("Interceptions", "interceptions")
        add_line("Clearances", "clearances")
        add_line("Blocks", "blocks")
        add_line("Possession won final 3rd", "poss_won_att_3rd")
        add_line("Fouls committed", "fouls_committed")
        add_line("Yellow cards", "yellow_cards")
        add_line("Red cards", "red_cards")

        if "xgot" in metrics and "xg" in metrics:
            finishing_delta = metrics["xgot"] - metrics["xg"]
            lines.append(f"Finishing delta (xGOT-xG): {_format_number(finishing_delta)}")

    return "\n".join(lines)
