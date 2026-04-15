import asyncio
import html
import logging
import re

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
from sofascore_client import SofascoreClient
from team_client import TeamDataClient
from llm_client import LLMClient
from orchestrator import execute_query


def md_to_html(text: str) -> str:
    """Convert AI markdown output to Telegram-compatible HTML."""
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\w)\*(.+?)\*(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!\w)_(.+?)_(?!\w)', r'<i>\1</i>', text)
    text = re.sub(r'`(.+?)`', r'<code>\1</code>', text)
    text = re.sub(r'^#{1,3}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
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

    # LLM client
    llm = LLMClient(
        api_key=config.OPENROUTER_API_KEY,
        models_config={
            "heavy": config.MODEL_ANALYSIS,
            "light": config.MODEL_TRANSLATE,
            "search": config.MODEL_SEARCH,
            "router": config.MODEL_ORCHESTRATOR,
        },
    )

    # Shared clients dict for tools
    clients = {
        "resolver": resolver,
        "usc": usc,
        "sofa": sofa,
        "team_client": team_client,
        "db": db,
        "llm": llm,
    }

    # Cache for orchestrator results
    ai_result_cache: TTLCache = TTLCache(maxsize=256, ttl=24 * 60 * 60)

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        count = db.player_count()
        await message.answer(
            f"Привет! В базе {count} игроков из 6 топ-лиг.\n"
            "Отправь имя — пришлю статистику за текущий сезон.\n"
            "Сравнить: «Салах vs Мбаппе» или «сравни Холанда и Палмера»\n"
            "Матчи: «Фоден последний матч» или «Ямал против Реала»\n"
            "Тренеры: «тренер Ливерпуля» или «Гвардиола vs Артета»\n"
            "/clearcache — очистить кэш"
        )

    @dp.message(Command("clearcache"))
    async def on_clearcache(message: Message) -> None:
        ai_result_cache.clear()
        usc._season_cache.clear()
        usc._match_cache.clear()
        sofa._stats_cache.clear()
        sofa._id_cache.clear()
        await message.answer("Кэш очищен.")

    @dp.message(F.text)
    async def handle_query(message: Message) -> None:
        query = extract_query(message, bot_username)
        if not query:
            if message.chat.type in {"group", "supergroup"}:
                return
            await message.answer("Нужен текстовый запрос с именем игрока.")
            return

        # Check cache
        cache_key = query.strip().lower()[:128]
        cached = ai_result_cache.get(cache_key)
        if cached:
            for chunk in split_message(cached):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
            return

        status_msg = await message.answer("Анализирую...")

        try:
            result = await execute_query(query, llm, clients)
            html_result = md_to_html(result)
            ai_result_cache[cache_key] = html_result

            # Delete status message
            try:
                await status_msg.delete()
            except Exception:
                pass

            for chunk in split_message(html_result):
                await message.answer(chunk, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.exception("Orchestrator failed")
            try:
                await status_msg.delete()
            except Exception:
                pass
            await message.answer(f"Ошибка: {type(e).__name__}: {e}")

    return bot, dp, db


async def main() -> None:
    bot, dp, db = await create_bot()
    try:
        await dp.start_polling(bot)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
