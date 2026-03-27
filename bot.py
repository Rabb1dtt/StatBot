import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message

import config
from database import PlayerDB
from understat_sync import sync_player_ids_async
from understat_client import UnderstatPlayerClient
from name_resolver import NameResolver
from cachetools import TTLCache
from stats_formatter import format_player_stats, format_match_breakdown
from sofascore_client import SofascoreClient, format_sofascore_extra
from ai_analyzer import AIAnalyzer


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
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
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
            "Сравнить: «Салах vs Мбаппе» или «сравни Холанда и Палмера»"
        )

    async def _fetch_stats(name: str) -> tuple[str | None, str | None]:
        """Resolve + fetch stats. Returns (formatted_text, error). Cached 24h by player ID."""
        resolved = await resolver.resolve(name)
        if not resolved:
            return None, f"Не нашёл игрока «{name}». Доступны 6 лиг: EPL, La Liga, Serie A, Bundesliga, Ligue 1, РПЛ."

        # Check cache
        cached = player_text_cache.get(resolved.understat_id)
        if cached:
            logger.info("Cache hit: %s (id=%d)", resolved.name, resolved.understat_id)
            return cached, None

        season = await usc.get_current_season(resolved.understat_id)
        if not season:
            return None, f"Нет статистики за текущий сезон для {resolved.name}."

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
            sofa_stats = await sofa.get_player_stats(resolved.name, resolved.league)
            extra = format_sofascore_extra(sofa_stats) if sofa_stats else ""
            if extra:
                text += "\n\n" + extra
        except Exception:
            logger.exception("sofascore fetch failed")

        # Cache the final text
        player_text_cache[resolved.understat_id] = text
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

        if qtype == "compare" and len(names) >= 2:
            await _handle_compare(message, names[0], names[1])
        else:
            await _handle_single(message, names[0] if names else query)

    async def _handle_single(message: Message, name: str) -> None:
        try:
            raw_text, err = await _fetch_stats(name)
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
                await message.answer(chunk, parse_mode=None)
            return

        final_text = await analyzer.analyze(raw_text)
        text = final_text or raw_text
        if final_text:
            ai_result_cache[ai_cache_key] = final_text
        for chunk in split_message(text):
            await message.answer(chunk, parse_mode=None if final_text else ParseMode.MARKDOWN)

    async def _handle_compare(message: Message, name1: str, name2: str) -> None:
        await message.answer(f"Ищу {name1} и {name2}...")

        try:
            text1, err1 = await _fetch_stats(name1)
            text2, err2 = await _fetch_stats(name2)
        except Exception as e:
            logger.exception("compare fetch failed")
            await message.answer(f"Ошибка: {type(e).__name__}: {e}")
            return

        if err1:
            await message.answer(err1)
            return
        if err2:
            await message.answer(err2)
            return

        final_text = await analyzer.compare(text1, text2)
        if final_text:
            for chunk in split_message(final_text):
                await message.answer(chunk, parse_mode=None)
        else:
            combined = f"=== ИГРОК 1 ===\n{text1}\n\n=== ИГРОК 2 ===\n{text2}"
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
