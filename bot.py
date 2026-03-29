import asyncio
import html
import logging
import re
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

import config
from database import PlayerDB
from understat_sync import sync_player_ids_async
from understat_client import UnderstatPlayerClient
from name_resolver import NameResolver
from cachetools import TTLCache
from stats_formatter import format_player_stats, format_match_breakdown
from sofascore_client import SofascoreClient, format_sofascore_extra, format_cup_matches, CUP_TOURNAMENT_IDS, LEAGUE_TOURNAMENT_IDS
from team_client import TeamDataClient, format_team_data, UNDERSTAT_LEAGUES
from ai_analyzer import AIAnalyzer


def md_to_html(text: str) -> str:
    """Convert AI markdown output to Telegram-compatible HTML."""
    # Escape HTML entities first (but preserve existing tags if any)
    text = html.escape(text)

    # **bold** or __bold__ → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # *italic* or _italic_ (but not inside words like player_name)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text)

    # `code` → <code>code</code>
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)

    # ### heading or ## heading or # heading → <b>heading</b>
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # --- or ___ horizontal rule → just a line
    text = re.sub(r'^[\-_]{3,}$', '———', text, flags=re.MULTILINE)

    return text


def extract_query(message: Message, bot_username: str) -> str | None:
    text = (message.text or "").strip()
    if not text:
        return None

    if message.chat.type in {"group", "supergroup"}:
        entities = message.entities or []
        mentions = [
            text[e.offset : e.offset + e.length]
            for e in entities
            if e.type == "mention"
        ]
        has_entity_mention = any(m.lower() == f"@{bot_username}" for m in mentions)
        pattern = re.compile(rf"@{re.escape(bot_username)}", re.IGNORECASE)
        has_text_mention = bool(pattern.search(text))

        if not (has_entity_mention or has_text_mention):
            return None
        cleaned = pattern.sub("", text)
        cleaned = cleaned.replace(f"@@{bot_username}", "")
        cleaned = cleaned.strip()
        return cleaned or None

    return text


def split_message(text: str, limit: int = 4096) -> list[str]:
    text = text.strip()
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while len(text) > limit:
        split_at = text.rfind("\n\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = text.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunk = text[:split_at].strip()
        if not chunk:
            chunk = text[:limit]
            split_at = limit
        parts.append(chunk)
        text = text[split_at:].lstrip()
    if text:
        parts.append(text)
    return parts


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_bot() -> tuple[Bot, Dispatcher, PlayerDB]:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    me = await bot.get_me()
    bot_username = (me.username or "").lower()

    # Database
    db = PlayerDB()
    db.open()

    # Sync player IDs if DB is empty
    if db.is_empty():
        logger.info("DB is empty, syncing player IDs from Understat...")
        count = await sync_player_ids_async(db)
        logger.info("Loaded %d players into DB", count)

    # Components
    usc = UnderstatPlayerClient()
    sofa = SofascoreClient()
    await sofa.start()
    team_client = TeamDataClient()
    resolver = NameResolver(db)
    resolver.rebuild_index()
    analyzer = AIAnalyzer()
    player_text_cache: TTLCache = TTLCache(maxsize=256, ttl=24 * 60 * 60)
    ai_result_cache: TTLCache = TTLCache(maxsize=256, ttl=24 * 60 * 60)

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        count = db.player_count()
        await message.answer(
            f"Привет! В базе {count} игроков из 6 топ-лиг.\n"
            "Отправь имя — пришлю статистику за текущий сезон.\n"
            "Сравнить: «Салах vs Мбаппе» или «сравни Холанда и Палмера»\n"
            "/clearcache — очистить кэш"
        )

    @dp.message(Command("clearcache"))
    async def on_clearcache(message: Message) -> None:
        player_text_cache.clear()
        ai_result_cache.clear()
        usc._season_cache.clear()
        usc._match_cache.clear()
        sofa._stats_cache.clear()
        sofa._id_cache.clear()
        await message.answer("Кэш очищен.")

    async def _fetch_stats(name: str, team_hint: str | None = None, season_year: str | None = None) -> tuple[str | None, str | None]:
        """Resolve + fetch stats. Returns (formatted_text, error). Cached 24h by player ID + season."""
        resolved = await resolver.resolve(name, team_hint=team_hint)
        if not resolved:
            return None, f"Не нашёл игрока «{name}». Доступны 6 лиг: EPL, La Liga, Serie A, Bundesliga, Ligue 1, РПЛ."

        # Check cache (include season in key)
        cache_key = (resolved.understat_id, season_year or "current")
        cached = player_text_cache.get(cache_key)
        if cached:
            logger.info("Cache hit: %s (id=%d, season=%s)", resolved.name, resolved.understat_id, season_year)
            return cached, None

        target_season = season_year or "2025"
        season = await usc.get_current_season(resolved.understat_id, season=target_season)
        if not season:
            return None, f"Нет статистики за сезон {target_season}/{int(target_season)+1} для {resolved.name}."

        text = format_player_stats(
            name=resolved.name,
            team=resolved.team,
            league=resolved.league,
            position=resolved.position,
            stats=season,
        )

        # Add per-opponent breakdown
        try:
            matches = await usc.get_match_stats(resolved.understat_id)
            breakdown = format_match_breakdown(resolved.team, matches, season.get("season", "2025"))
            if breakdown:
                text += "\n\n" + breakdown
        except Exception:
            logger.exception("match breakdown failed")

        # Add SofaScore dribbling/duels data
        try:
            sofa_stats = await sofa.get_player_stats(resolved.name, resolved.league, season_year=season_year)
            extra = format_sofascore_extra(sofa_stats) if sofa_stats else ""
            if extra:
                text += "\n\n" + extra
        except Exception:
            logger.exception("sofascore fetch failed")

        # Add cup/european match stats
        try:
            sofa_player = await sofa.search_player(resolved.name)
            if sofa_player:
                if season_year and season_year != "2025":
                    # Historical: paginate deep, filter by season dates, include cups
                    cup_matches = await sofa.get_player_cup_matches_by_date(
                        sofa_player["id"], CUP_TOURNAMENT_IDS,
                        date_from=f"{season_year}-08-01",
                        date_to=f"{int(season_year)+1}-06-30",
                        max_pages=15,
                    )
                else:
                    cup_matches = await sofa.get_cup_match_stats(
                        sofa_player["id"], CUP_TOURNAMENT_IDS, max_matches=15,
                    )
                cup_text = format_cup_matches(cup_matches)
                if cup_text:
                    text += "\n\n" + cup_text
        except Exception:
            logger.exception("cup stats fetch failed")

        # Add league standings
        try:
            standings = await sofa.get_league_top10(resolved.league, season_year=season_year)
            if standings:
                text += "\n\n" + standings
        except Exception:
            logger.exception("standings fetch failed")

        # Cache the final text
        player_text_cache[cache_key] = text
        return text, None

    @dp.message(F.text)
    async def handle_query(message: Message) -> None:
        query = extract_query(message, bot_username)
        if not query:
            if message.chat.type in {"group", "supergroup"}:
                return
            await message.answer("Нужен текстовый запрос с именем игрока.")
            return

        await message.answer("Анализирую запрос...")

        try:
            parsed = await resolver.parse_query(query)
        except Exception:
            logger.exception("parse_query failed")
            parsed = {"type": "single", "names": [query]}

        qtype = parsed["type"]
        names = parsed["names"]
        hints = parsed.get("team_hints", [None] * len(names))

        if qtype == "compare_coaches":
            await message.answer("Ищу актуальную информацию о тренерах...")
            coach_names_list = parsed.get("coach_names", [])
            teams_list = parsed.get("teams", [])

            # For each coach, search for dates (team already from Sonnet)
            leagues_list = parsed.get("leagues", [])
            resolved_coaches = []
            for i, cn in enumerate(coach_names_list):
                team = teams_list[i] if i < len(teams_list) else ""
                league = leagues_list[i] if i < len(leagues_list) else ""

                # Search for dates at this specific team
                info = await resolver.search_specific_coach(cn, team or cn)

                # If no team from Sonnet, try search_coach_info
                if not team and info is None:
                    team_info = await resolver.search_coach_info(cn)
                    if team_info:
                        team = team_info.get("team", "")
                        league = team_info.get("league", "")
                        info = {"coach_since": team_info.get("coach_since")}

                resolved_coaches.append({
                    "coach_name": cn,
                    "team": team,
                    "league": league,
                    "coach_since": info.get("coach_since") if info else None,
                    "coach_until": info.get("coach_until") if info else None,
                })
                logger.info("Resolved coach: %s → %s (%s) since=%s until=%s",
                           cn, team, league,
                           info.get("coach_since") if info else "?",
                           info.get("coach_until") if info else "?")

            if not resolved_coaches:
                # Fallback to team-based comparison
                await _handle_compare_coaches_by_teams(message, teams_list, parsed.get("leagues", []))
            else:
                await _handle_compare_coaches_resolved(message, resolved_coaches)

        elif qtype == "coach":
            await message.answer("Ищу актуальную информацию о тренере...")
            team_name = parsed.get("team", names[0] if names else query)
            coach_name = parsed.get("coach_name")

            if coach_name:
                sonnet_has_dates = parsed.get("coach_since") and parsed.get("coach_until")
                if not sonnet_has_dates:
                    search_info = await resolver.search_specific_coach(coach_name, team_name)
                    if search_info:
                        if not parsed.get("coach_since"):
                            parsed["coach_since"] = search_info.get("coach_since")
                        if not parsed.get("coach_until"):
                            parsed["coach_until"] = search_info.get("coach_until")

                # Try to detect season from query text: "2024-2025" → since=2024-08, until=2025-06
                if not parsed.get("coach_until") and not parsed.get("all_time"):
                    import re as _re
                    season_match = _re.search(r'(\d{4})\s*[-/]\s*(\d{4})', query)
                    if season_match:
                        y1, y2 = season_match.group(1), season_match.group(2)
                        parsed["coach_since"] = f"{y1}-08-01"
                        parsed["coach_until"] = f"{y2}-06-30"
                        logger.info("Season from query: %s → %s", parsed["coach_since"], parsed["coach_until"])

                # If coach is CURRENT (no until), no specific season, and NOT all_time →
                # default to current season only
                if (not parsed.get("coach_until")
                        and parsed.get("coach_since")
                        and not parsed.get("all_time")):
                    current_season_start = "2025-08-01"
                    if parsed["coach_since"] < current_season_start:
                        parsed["coach_since"] = current_season_start
                        logger.info("Limiting to current season: since=%s", parsed["coach_since"])

                # Check which team if not set
                if not parsed.get("team") or not parsed.get("league"):
                    team_info = await resolver.search_coach_info(coach_name)
                    if team_info:
                        if not parsed.get("team") or parsed["team"] == coach_name:
                            parsed["team"] = team_info.get("team", team_name)
                        if not parsed.get("league"):
                            parsed["league"] = team_info.get("league")
            else:
                search_info = await resolver.search_coach_info(team_name)
                if search_info:
                    parsed["coach_name"] = search_info.get("coach_name")
                    parsed["coach_since"] = search_info.get("coach_since")
                    if not parsed.get("league"):
                        parsed["league"] = search_info.get("league")
                    if not parsed.get("team"):
                        parsed["team"] = search_info.get("team", team_name)

            await _handle_team(
                message,
                team_name=parsed.get("team", team_name),
                league=parsed.get("league"),
                mode=qtype,
                coach_name=parsed.get("coach_name"),
                coach_since=parsed.get("coach_since"),
                coach_until=parsed.get("coach_until"),
            )
        elif qtype == "team":
            await _handle_team(
                message,
                team_name=parsed.get("team", names[0] if names else query),
                league=parsed.get("league"),
                mode=qtype,
            )
        elif qtype == "match":
            hint = hints[0] if hints else None
            await _handle_match(
                message,
                names[0] if names else query,
                hint,
                opponent=parsed.get("opponent"),
                tournament_filter=parsed.get("tournament"),
                count=parsed.get("count"),
                all_time=parsed.get("all_time", False),
            )
        elif qtype == "compare" and len(names) >= 2:
            await _handle_compare(message, names[:5], hints[:5], season_year=parsed.get("season"))
        else:
            hint = hints[0] if hints else None
            await _handle_single(message, names[0] if names else query, hint, season_year=parsed.get("season"))

    async def _handle_single(message: Message, name: str, team_hint: str | None = None, season_year: str | None = None) -> None:
        try:
            raw_text, err = await _fetch_stats(name, team_hint, season_year=season_year)
        except Exception as e:
            logger.exception("fetch failed")
            await message.answer(f"Ошибка: {type(e).__name__}: {e}")
            return

        if err:
            await message.answer(err)
            return

        # Check AI cache
        ai_cache_key = f"single:{raw_text[:64]}"
        cached_ai = ai_result_cache.get(ai_cache_key)
        if cached_ai:
            logger.info("AI cache hit for %s", name)
            for chunk in split_message(cached_ai):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
            return

        final_text = await analyzer.analyze(raw_text)
        if final_text:
            result = md_to_html(final_text)
            ai_result_cache[ai_cache_key] = result
            for chunk in split_message(result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        else:
            for chunk in split_message(raw_text):
                await message.answer(chunk)

    async def _fetch_team_full(team_name: str, league: str, coach_name: str | None = None, coach_since: str | None = None, coach_until: str | None = None) -> tuple[str | None, str | None]:
        """Fetch team data from Understat + SofaScore. Returns (formatted_text, error)."""
        us_league = UNDERSTAT_LEAGUES.get(league)
        has_understat = us_league is not None

        team_data = None
        if has_understat:
            try:
                team_data = await team_client.get_team_season(team_name, league, coach_since=coach_since, coach_until=coach_until)
            except Exception as e:
                logger.warning("Understat failed for %s: %s", team_name, e)

        if not team_data:
            # No Understat data — build minimal structure, will rely on SofaScore
            team_data = {
                "title": team_name, "matches": 0, "wins": 0, "draws": 0, "losses": 0,
                "points": 0, "ppg": 0, "goals": 0, "conceded": 0, "gd": 0,
                "xG": 0, "xGA": 0, "xGD": 0, "npxG": 0, "npxGA": 0,
                "goals_minus_xG": 0, "conceded_minus_xGA": 0,
                "ppda": 0, "oppda": 0, "deep": 0, "deep_allowed": 0, "deep_per_match": 0,
                "form": [], "first_date": "?", "last_date": "?",
            }
            if has_understat:
                logger.warning("No Understat data for %s in %s", team_name, league)
            else:
                logger.info("League %s not in Understat, using SofaScore only", league)

        # SofaScore team stats are season-wide, not per-coach period.
        # Skip them if coach_until is set (partial season = stats would be misleading)
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
                        # Manager
                        team_info = await sofa._get(f"/team/{sofa_team_id}")
                        if team_info:
                            manager = team_info.get("team", {}).get("manager")

                        # Stats (skip if partial season — would be misleading for coach comparison)
                        if not skip_sofa_stats:
                            us_league = UNDERSTAT_LEAGUES.get(league, league)
                            ut_id = LEAGUE_TOURNAMENT_IDS.get(us_league)
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

        # Auto-detect coach departure via search if not already set
        if coach_name and not coach_until and manager:
            current_mgr = manager.get("name", "")
            if current_mgr and current_mgr.lower() != coach_name.lower():
                logger.info("Coach mismatch: %s vs current %s, searching for departure date", coach_name, current_mgr)
                try:
                    info = await resolver.search_specific_coach(coach_name, team_name)
                    if info and info.get("coach_until"):
                        coach_until = info["coach_until"]
                        logger.info("Search says %s left on %s", coach_name, coach_until)
                        team_data = await team_client.get_team_season(team_name, league, coach_since=coach_since, coach_until=coach_until)
                        if not team_data:
                            return None, f"Нет данных за период {coach_since} — {coach_until}."
                except Exception:
                    logger.exception("coach departure search failed")

        standings = None
        try:
            us_league = UNDERSTAT_LEAGUES.get(league, league)
            standings = await sofa.get_league_top10(us_league)
        except Exception:
            pass

        # Cup/European results from SofaScore team events
        # If no Understat → fetch ALL matches (including league) from SofaScore
        cup_results = []
        sofa_league_results = []
        try:
            if sofa_team_id:
                # More pages for all_time or non-understat leagues
                if not has_understat:
                    max_pages = 10
                elif coach_since and coach_since < "2024-01-01":
                    max_pages = 25  # multi-season tenure
                else:
                    max_pages = 3
                team_events = await sofa.get_team_events(sofa_team_id, max_pages=max_pages)
                league_tid = LEAGUE_TOURNAMENT_IDS.get(us_league) if us_league else None
                for e in team_events:
                    tid = e.get("tournament", {}).get("uniqueTournament", {}).get("id")
                    # If we have Understat, skip league matches (already covered)
                    is_league = (tid == league_tid) if league_tid else False
                    if is_league and has_understat:
                        continue
                    # Filter by coach date range
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

                    # Determine result
                    is_home = team_name.lower() in home.lower()
                    gf = hs if is_home else aws
                    ga = aws if is_home else hs
                    if gf > ga:
                        result = "w"
                    elif gf == ga:
                        result = "d"
                    else:
                        result = "l"

                    # Stage tag
                    stage = ""
                    rn = str(rname).lower()
                    if any(k in rn for k in ["final"]):
                        stage = "ФИНАЛ" if "semi" not in rn else "ПОЛУФИНАЛ"
                    elif "semi" in rn:
                        stage = "ПОЛУФИНАЛ"
                    elif "quarter" in rn:
                        stage = "ЧЕТВЕРТЬФИНАЛ"

                    cup_results.append({
                        "tournament": tname,
                        "round": str(rname),
                        "stage": stage,
                        "home": home,
                        "away": away,
                        "score": f"{hs}-{aws}",
                        "_date": match_date if ts else "",
                        "goals_for": gf,
                        "goals_against": ga,
                        "result": result,
                    })
        except Exception:
            logger.exception("cup results fetch failed")

        # Re-filter cup_results by coach_until (may have been updated after departure detection)
        if coach_until and cup_results:
            cup_results = [c for c in cup_results
                          if not c.get("_date") or c["_date"] <= coach_until]

        # If no Understat data, build team_data from SofaScore events
        if not has_understat or team_data.get("matches", 0) == 0:
            all_sofa = cup_results  # all events are in cup_results when no Understat
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
                logger.info("Built team_data from %d SofaScore events for %s", matches, team_name)

        text = format_team_data(team_data, sofa_team_stats, standings, manager, coach_name, coach_since, cup_results, coach_until)
        return text, None

    async def _handle_compare_coaches_resolved(message: Message, coaches: list[dict]) -> None:
        """Compare coaches: run full single analysis for each, then compare."""
        if len(coaches) < 2:
            await message.answer("Нужно минимум 2 тренера для сравнения.")
            return

        # Auto-fill coach_until: if two coaches at same club, earlier one's until = later one's since
        coaches_sorted = sorted(coaches, key=lambda c: c.get("coach_since") or "9999")
        for i in range(len(coaches_sorted) - 1):
            if (coaches_sorted[i].get("team", "").lower() == coaches_sorted[i+1].get("team", "").lower()
                    and not coaches_sorted[i].get("coach_until")
                    and coaches_sorted[i+1].get("coach_since")):
                coaches_sorted[i]["coach_until"] = coaches_sorted[i+1]["coach_since"]
                logger.info("Auto-set %s coach_until=%s (next coach %s started)",
                           coaches_sorted[i]["coach_name"], coaches_sorted[i]["coach_until"],
                           coaches_sorted[i+1]["coach_name"])

        coach_labels = [f"{c['coach_name']} ({c['team']})" for c in coaches_sorted]
        await message.answer(f"Собираю данные: {', '.join(coach_labels)}...")

        # Run full single-coach analysis for each
        raw_texts = []
        for c in coaches_sorted:
            if not c.get("league"):
                await message.answer(f"Не удалось определить лигу для {c['coach_name']}.")
                return
            try:
                logger.info("Fetching full coach data: %s at %s (%s) %s→%s",
                           c["coach_name"], c["team"], c["league"], c.get("coach_since"), c.get("coach_until"))
                text, err = await _fetch_team_full(
                    c["team"], c["league"],
                    coach_name=c["coach_name"],
                    coach_since=c.get("coach_since"),
                    coach_until=c.get("coach_until"),
                )
                if err:
                    await message.answer(f"{c['coach_name']}: {err}")
                    return

                # Get individual AI analysis first (like single coach request)
                single_analysis = await analyzer.analyze_coach(text)
                if single_analysis:
                    raw_texts.append(f"ТРЕНЕР: {c['coach_name']} ({c['team']})\n\nСЫРЫЕ ДАННЫЕ:\n{text}\n\nАНАЛИЗ:\n{single_analysis}")
                else:
                    raw_texts.append(f"ТРЕНЕР: {c['coach_name']} ({c['team']})\n\n{text}")
            except Exception as e:
                logger.exception("Failed to fetch data for %s", c["coach_name"])
                await message.answer(f"Ошибка для {c['coach_name']}: {type(e).__name__}: {e}")
                return

        # Now compare the full analyses
        try:
            final = await analyzer.compare_coaches(raw_texts)
            if final:
                result = md_to_html(final)
                for chunk in split_message(result):
                    await message.answer(chunk, parse_mode=ParseMode.HTML)
            else:
                combined = "\n\n———\n\n".join(raw_texts)
                for chunk in split_message(combined):
                    await message.answer(chunk)
        except Exception as e:
            logger.exception("compare_coaches failed")
            await message.answer(f"Ошибка сравнения: {type(e).__name__}: {e}")

    async def _handle_compare_coaches_by_teams(message: Message, teams: list[str], leagues: list[str]) -> None:
        """Fallback: compare by team names (when coach names not available)."""
        if len(teams) < 2:
            await message.answer("Нужно минимум 2 команды для сравнения.")
            return

        await message.answer(f"Сравниваю: {', '.join(teams)}...")

        team_texts = []
        for i, team_name in enumerate(teams):
            league = leagues[i] if i < len(leagues) else leagues[0] if leagues else None
            if not league:
                await message.answer(f"Не удалось определить лигу для {team_name}.")
                return
            text, err = await _fetch_team_full(team_name, league)
            if err:
                await message.answer(err)
                return
            team_texts.append(text)

        # AI comparison
        final = await analyzer.compare_coaches(team_texts)
        if final:
            result = md_to_html(final)
            for chunk in split_message(result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        else:
            combined = "\n\n".join(f"=== {teams[i]} ===\n{t}" for i, t in enumerate(team_texts))
            for chunk in split_message(combined):
                await message.answer(chunk)

    async def _handle_team(message: Message, team_name: str, league: str | None, mode: str = "team", coach_name: str | None = None, coach_since: str | None = None, coach_until: str | None = None) -> None:
        """Handle coach or team season analysis."""
        if not league:
            await message.answer("Не удалось определить лигу. Уточни: 'тренер Ливерпуля АПЛ'.")
            return

        await message.answer(f"Собираю данные по {team_name}...")

        raw_text, err = await _fetch_team_full(team_name, league, coach_name, coach_since, coach_until)
        if err:
            await message.answer(err)
            return

        # AI
        if mode == "coach":
            final = await analyzer.analyze_coach(raw_text)
        else:
            final = await analyzer.analyze_team(raw_text)

        if final:
            result = md_to_html(final)
            for chunk in split_message(result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        else:
            for chunk in split_message(raw_text):
                await message.answer(chunk)

    async def _handle_match(
        message: Message, name: str, team_hint: str | None,
        opponent: str | None = None, tournament_filter: str | None = None,
        count: int | None = None, all_time: bool = False,
    ) -> None:
        """Analyze a player's performance in specific match(es)."""
        resolved = await resolver.resolve(name, team_hint=team_hint)
        if not resolved:
            await message.answer(f"Не нашёл игрока «{name}».")
            return

        # Find SofaScore player
        sofa_player = await sofa.search_player(resolved.name)
        if not sofa_player:
            await message.answer(f"Не нашёл {resolved.name} на SofaScore.")
            return

        player_id = sofa_player["id"]
        await message.answer(f"Ищу матчи {resolved.name}...")

        # Determine how many pages to fetch
        max_pages = 15 if all_time else 3

        # Get events
        all_events = []
        for page in range(max_pages):
            events = await sofa.get_player_events(player_id, page)
            if not events:
                break
            all_events.extend(events)

        # Sort all by date descending (most recent first)
        all_events.sort(key=lambda e: e.get("startTimestamp", 0), reverse=True)

        if not all_events:
            await message.answer("Не нашёл матчей.")
            return

        # Opponent name for matching (Sonnet already returns English names)
        opp_lower = None
        if opponent:
            opp_lower = opponent.lower()
            logger.info("Match filter: opponent=%s, tournament=%s, count=%s", opponent, tournament_filter, count)

        # Transliterate tournament filter
        tourney_lower = None
        if tournament_filter:
            tourney_lower = tournament_filter.lower()

        # Filter events
        target_events = []
        for e in all_events:
            home = e.get("homeTeam", {}).get("name", "")
            away = e.get("awayTeam", {}).get("name", "")
            tourney_name = e.get("tournament", {}).get("uniqueTournament", {}).get("name", "")

            # Filter by opponent
            if opp_lower:
                if opp_lower not in home.lower() and opp_lower not in away.lower():
                    continue

            # Filter by tournament
            if tourney_lower:
                if tourney_lower not in tourney_name.lower():
                    continue

            target_events.append(e)

        # No filters and nothing found → take last match
        if not target_events and not opponent:
            target_events = [all_events[0]]

        logger.info("Match search: %d events total, %d after filter (opp=%s, tour=%s)",
                     len(all_events), len(target_events), opp_lower, tourney_lower)

        # Apply count limit
        if count and count > 0:
            target_events = target_events[:count]

        if not target_events:
            filter_desc = opponent or "?"
            if tournament_filter:
                filter_desc += f" в {tournament_filter}"
            await message.answer(f"Не нашёл матчей {resolved.name} против «{filter_desc}».")
            return

        # Collect stats for all matching matches
        # Sort chronologically for display (oldest first)
        if len(target_events) > 1:
            target_events.sort(key=lambda e: e.get("startTimestamp", 0))

        all_lines = []
        all_lines.append(f"Игрок: {resolved.name} ({resolved.team})")
        if len(target_events) > 1:
            all_lines.append(f"Найдено матчей: {len(target_events)} (хронологический порядок)")
        all_lines.append("")

        stat_labels = {
            "goals": "Голы", "goalAssist": "Ассисты",
            "expectedGoals": "xG", "expectedAssists": "xA",
            "totalShots": "Удары", "shotsOnTarget": "В створ",
            "accuratePass": "Точные пасы", "totalPass": "Всего пасов",
            "accurateLongBalls": "Точные длинные", "totalLongBalls": "Длинные",
            "accurateCross": "Точные кроссы", "totalCross": "Кроссы",
            "keyPass": "Ключевые передачи",
            "tackles": "Отборы", "interceptions": "Перехваты",
            "totalClearance": "Выносы", "ballRecovery": "Возвраты мяча",
            "duelWon": "Единоборства выиграны", "duelLost": "Единоборства проиграны",
            "aerialWon": "Воздушные выиграны", "aerialLost": "Воздушные проиграны",
            "successfulDribbles": "Обводки", "dribbleAttempts": "Попытки обводок",
            "touches": "Касания",
            "fouls": "Фолы", "wasFouled": "Заработал фолы",
            "saves": "Сейвы",
            "goalsPrevented": "Предотвращённые голы",
        }

        for ev in target_events:
            event_id = ev["id"]
            home = ev.get("homeTeam", {}).get("name", "?")
            away = ev.get("awayTeam", {}).get("name", "?")
            h_score = ev.get("homeScore", {}).get("current", "?")
            a_score = ev.get("awayScore", {}).get("current", "?")
            tournament = ev.get("tournament", {}).get("uniqueTournament", {}).get("name", "?")
            round_info = ev.get("roundInfo", {})
            round_name = round_info.get("name", round_info.get("round", "?"))

            # Date
            ts = ev.get("startTimestamp", 0)
            from datetime import datetime, timezone
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d.%m.%Y") if ts else "?"

            stats = await sofa.get_player_event_stats(event_id, player_id)
            if not stats:
                all_lines.append(f"*{home} {h_score}-{a_score} {away}* ({date_str}, {tournament} R{round_name}) — нет данных")
                all_lines.append("")
                continue

            mins = stats.get("minutesPlayed", 0)
            rating = stats.get("rating", "—")

            all_lines.append(f"*{home} {h_score}-{a_score} {away}*")
            all_lines.append(f"Дата: {date_str} | Турнир: {tournament}, раунд {round_name}")
            all_lines.append(f"Минут: {mins} | Рейтинг: {rating}")

            for key, label in stat_labels.items():
                val = stats.get(key)
                if val is not None and val != 0:
                    if isinstance(val, float):
                        all_lines.append(f"  {label}: {val:.2f}")
                    else:
                        all_lines.append(f"  {label}: {val}")
            all_lines.append("")

        raw_text = "\n".join(all_lines)

        # AI analysis
        final = await analyzer.analyze_match(raw_text)
        if final:
            result = md_to_html(final)
            for chunk in split_message(result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        else:
            for chunk in split_message(raw_text):
                await message.answer(chunk)

    async def _handle_compare(message: Message, names: list[str], hints: list[str | None] | None = None, season_year: str | None = None) -> None:
        await message.answer(f"Ищу {', '.join(names)}...")

        if not hints:
            hints = [None] * len(names)

        player_texts: list[str] = []
        for name, hint in zip(names, hints):
            try:
                text, err = await _fetch_stats(name, hint, season_year=season_year)
            except Exception as e:
                logger.exception("compare fetch failed for %s", name)
                await message.answer(f"Ошибка для {name}: {type(e).__name__}: {e}")
                return
            if err:
                await message.answer(err)
                return
            player_texts.append(text)

        # Check AI cache for this comparison
        compare_key = "compare:" + "|".join(sorted(t[:32] for t in player_texts))
        cached_ai = ai_result_cache.get(compare_key)
        if cached_ai:
            logger.info("AI compare cache hit")
            for chunk in split_message(cached_ai):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
            return

        final_text = await analyzer.compare(player_texts)
        if final_text:
            result = md_to_html(final_text)
            ai_result_cache[compare_key] = result
            for chunk in split_message(result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        else:
            combined = "\n\n".join(
                f"=== ИГРОК {i+1} ===\n{t}" for i, t in enumerate(player_texts)
            )
            for chunk in split_message(combined):
                await message.answer(chunk)

    return bot, dp, db


async def main() -> None:
    bot, dp, db = await create_bot()
    try:
        await dp.start_polling(bot)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
