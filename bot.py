import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message
import re

import config
from fotmob_client import FotmobClient
from name_resolver import NameResolver
from stats_formatter import format_tournament_stats
from ai_analyzer import AIAnalyzer


def extract_query(message: Message, bot_username: str) -> str | None:
    """
    Возвращает строку запроса.
    В группах — только если есть упоминание бота (@username); упоминание убирается из текста.
    В личке — весь текст.
    """
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
        # убираем упоминание из текста (регистронезависимо)
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


async def create_bot() -> tuple[Bot, Dispatcher, FotmobClient, NameResolver]:
    if not config.BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Add it to .env")

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    me = await bot.get_me()
    bot_username = (me.username or "").lower()

    fotmob_client = FotmobClient()
    resolver = NameResolver(fotmob_client)
    analyzer = AIAnalyzer()
    await fotmob_client.start()

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            "Привет! Отправь имя футболиста на русском или латиницей — пришлю статистику за текущий сезон по турнирам."
        )

    @dp.message(F.text)
    async def handle_query(message: Message) -> None:
        query = extract_query(message, bot_username)
        if not query:
            # В группах отвечаем только на упоминание бота
            if message.chat.type in {"group", "supergroup"}:
                return
            await message.answer("Нужен текстовый запрос с именем игрока.")
            return

        await message.answer("Ищу игрока, секунду...")
        try:
            resolved = await resolver.resolve(query)
        except Exception as exc:  # network or LLM errors
            logger.exception("resolve failed")
            await message.answer("Не получилось распознать игрока. Попробуй ещё раз.")
            return

        if not resolved:
            await message.answer("Не нашёл такого игрока. Попробуй уточнить написание или клуб.")
            return

        try:
            season, tour_stats = await fotmob_client.get_current_season_tournament_stats(
                resolved.player_id
            )
            advanced = await fotmob_client.get_player_advanced_stats(resolved.player_id)
        except Exception:
            logger.exception("stat fetch failed")
            await message.answer("Не удалось получить статистику с FotMob.")
            return

        if not season or not tour_stats:
            await message.answer("Статистики за текущий сезон нет или игрок не активен.")
            return

        reply = format_tournament_stats(season, tour_stats, advanced)
        reply_header = f"*{resolved.name}*"
        if resolved.team:
            reply_header += f" ({resolved.team})"
        position = advanced.get("position") if advanced else None
        if position:
            reply_header += f" — {position}"

        raw_text = f"{reply_header}\n\n{reply}"
        final_text = await analyzer.analyze(raw_text)
        if final_text:
            for chunk in split_message(final_text):
                await message.answer(chunk, parse_mode=None)
        else:
            for chunk in split_message(raw_text):
                await message.answer(chunk)

    return bot, dp, fotmob_client, resolver


async def main() -> None:
    bot, dp, fotmob_client, _resolver = await create_bot()
    try:
        await dp.start_polling(bot)
    finally:
        await fotmob_client.close()


if __name__ == "__main__":
    asyncio.run(main())
