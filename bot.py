import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message

import config
from football_client import FootballClient
from name_resolver import NameResolver
from stats_formatter import format_player_stats
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


async def create_bot() -> tuple[Bot, Dispatcher, FootballClient, NameResolver]:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    me = await bot.get_me()
    bot_username = (me.username or "").lower()

    fc = FootballClient()
    await fc.start()
    resolver = NameResolver(fc)
    analyzer = AIAnalyzer()

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            "Привет! Отправь имя футболиста — пришлю статистику за сезон.\n"
            "Можно на русском или латиницей. Например: Салах, Mbappe, Холанд Сити"
        )

    @dp.message(F.text)
    async def handle_query(message: Message) -> None:
        query = extract_query(message, bot_username)
        if not query:
            if message.chat.type in {"group", "supergroup"}:
                return
            await message.answer("Нужен текстовый запрос с именем игрока.")
            return

        await message.answer("Ищу игрока, секунду...")
        try:
            resolved = await resolver.resolve(query)
        except Exception:
            logger.exception("resolve failed")
            await message.answer("Не получилось найти игрока. Попробуй ещё раз.")
            return

        if not resolved:
            await message.answer("Не нашёл такого игрока. Попробуй уточнить имя или добавить команду.")
            return

        try:
            player_data = await fc.get_player_by_id(resolved.player_id)
        except Exception:
            logger.exception("stat fetch failed")
            await message.answer("Не удалось получить статистику.")
            return

        if not player_data:
            await message.answer("Статистика не найдена.")
            return

        raw_text = format_player_stats(player_data)
        final_text = await analyzer.analyze(raw_text)
        if final_text:
            for chunk in split_message(final_text):
                await message.answer(chunk, parse_mode=None)
        else:
            for chunk in split_message(raw_text):
                await message.answer(chunk)

    return bot, dp, fc, resolver


async def main() -> None:
    bot, dp, fc, _resolver = await create_bot()
    try:
        await dp.start_polling(bot)
    finally:
        await fc.close()


if __name__ == "__main__":
    asyncio.run(main())
