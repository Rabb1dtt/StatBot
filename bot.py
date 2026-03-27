import asyncio
import logging
import re

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import CommandStart
from aiogram.types import Message

import config
from fotmob_client import FotmobClient
from name_resolver import NameResolver
from stats_formatter import format_player
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

    fc = FotmobClient()
    await fc.start()
    resolver = NameResolver(fc)
    analyzer = AIAnalyzer()

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            "Привет! Отправь имя футболиста — пришлю статистику за текущий сезон.\n"
            "Можно сравнить двух игроков: «Салах vs Мбаппе» или «сравни Холанда и Палмера»"
        )

    async def _fetch_player(name: str) -> tuple[str | None, str | None]:
        """Resolve + fetch + format a single player. Returns (formatted_text, error)."""
        resolved = await resolver.resolve(name)
        if not resolved:
            return None, f"Не нашёл игрока «{name}»."
        player_data = await fc.get_player(resolved.player_id, resolved.name)
        if not player_data:
            return None, f"Статистика «{resolved.name}» не найдена."
        return format_player(player_data), None

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
            raw_text, err = await _fetch_player(name)
        except Exception as e:
            logger.exception("fetch failed")
            await message.answer(f"Ошибка: {type(e).__name__}: {e}")
            return

        if err:
            await message.answer(err)
            return

        final_text = await analyzer.analyze(raw_text)
        text = final_text or raw_text
        for chunk in split_message(text):
            await message.answer(chunk, parse_mode=None if final_text else ParseMode.MARKDOWN)

    async def _handle_compare(message: Message, name1: str, name2: str) -> None:
        await message.answer(f"Ищу {name1} и {name2}...")

        try:
            text1, err1 = await _fetch_player(name1)
            text2, err2 = await _fetch_player(name2)
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
            # Fallback: just show both raw stats
            combined = f"=== ИГРОК 1 ===\n{text1}\n\n=== ИГРОК 2 ===\n{text2}"
            for chunk in split_message(combined):
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
