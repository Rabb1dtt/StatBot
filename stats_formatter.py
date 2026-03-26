from typing import Dict, List, Optional


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}" if not value.is_integer() else str(int(value))
    return str(value)


def _per90(total: float, minutes: Optional[float]) -> Optional[float]:
    if minutes is None or minutes <= 0:
        return None
    return total * 90.0 / minutes


def format_player(player: Dict) -> str:
    """Format FotMob player data into readable text."""
    name = player.get("name", "Unknown")
    position = _get_position(player)
    team = _get_team(player)

    lines: List[str] = []

    header = f"*{name}*"
    if team:
        header += f" ({team})"
    if position:
        header += f" — {position}"
    lines.append(header)

    # Player info
    info = player.get("playerInformation", [])
    info_parts = []
    for item in info:
        title = item.get("title", "")
        val = item.get("value", {})
        label = val.get("fallback") or val.get("value", "")
        if title and label:
            info_parts.append(f"{title}: {label}")
    if info_parts:
        lines.append(" | ".join(info_parts[:4]))
    lines.append("")

    # Season stats (firstSeasonStats)
    fss = player.get("firstSeasonStats", {})
    lines.append(_format_season_stats(fss, player))

    # Tournament breakdown from statSeasons
    seasons = player.get("statSeasons", [])
    if seasons:
        current = seasons[0]
        season_name = current.get("seasonName", "")
        tournaments = current.get("tournaments", [])
        if tournaments:
            lines.append(f"\n*Сезон {season_name}* — турниры:")
            for t in tournaments:
                lines.append(f"  • {t.get('name', '?')}")

    return "\n".join(lines)


def _get_position(player: Dict) -> Optional[str]:
    pd = player.get("positionDescription", {})
    if isinstance(pd, str):
        return pd
    if isinstance(pd, dict):
        primary = pd.get("primaryPosition")
        if isinstance(primary, dict):
            return primary.get("label")
        return pd.get("label")
    return None


def _get_team(player: Dict) -> Optional[str]:
    pt = player.get("primaryTeam", {})
    return pt.get("teamName")


def _format_season_stats(fss: Dict, player: Dict) -> str:
    if not fss:
        return "_Нет расширенной статистики_"

    lines: List[str] = []

    # Top stat card
    top_card = fss.get("topStatCard", {})
    if top_card:
        items = top_card.get("items", [])
        card_parts = []
        for item in items:
            title = item.get("title", "")
            per90 = item.get("per90")
            total = item.get("statValue")
            if title:
                s = f"{title}: {_fmt(total)}"
                if per90 is not None:
                    s += f" ({_fmt(per90)}/90)"
                card_parts.append(s)
        if card_parts:
            lines.append("*Ключевые показатели:*")
            for p in card_parts:
                lines.append(f"  {p}")
            lines.append("")

    # Stats sections
    stats_section = fss.get("statsSection")
    if stats_section and isinstance(stats_section, dict):
        _format_stats_section(stats_section, lines)
    elif isinstance(stats_section, list):
        for section in stats_section:
            _format_stats_section(section, lines)

    if not lines:
        return "_Нет расширенной статистики_"
    return "\n".join(lines)


def _format_stats_section(section: Dict, lines: List[str]) -> None:
    title = section.get("title", "")
    items = section.get("items", [])
    if not items:
        return

    if title:
        lines.append(f"*{title}:*")

    for item in items:
        label = item.get("title", "")
        total = item.get("statValue")
        per90 = item.get("per90")
        percentile = item.get("percentileRank")

        s = f"  {label}: {_fmt(total)}"
        if per90 is not None:
            s += f" ({_fmt(per90)}/90)"
        if percentile is not None:
            s += f" [top {100 - int(percentile)}%]"
        lines.append(s)
    lines.append("")
