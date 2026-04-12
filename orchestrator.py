"""AI orchestrator: TOOL_REGISTRY, pre-search, agentic loop, unified system prompt."""

import json
import logging
import re
from typing import Any

from llm_client import LLMClient
from tools.player import resolve_player, get_player_stats, get_match_breakdown
from tools.team import get_team_stats, get_coach_info
from tools.league import get_league_standings
from tools.search import search_web_context

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

# ── System prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """Ты — футбольный аналитик-эксперт для Telegram. У тебя есть инструменты для получения реальной статистики из Understat и SofaScore. На выходе — ОДИН удобочитаемый текст, без тех.терминов про "промт/эталоны/перевод", без "derived".

КАК ИСПОЛЬЗОВАТЬ ИНСТРУМЕНТЫ:
- Для игрока: вызови get_player_stats (включает Understat + SofaScore + кубки + таблицу)
- Для сравнения: вызови get_player_stats для КАЖДОГО игрока, затем сравни
- Для матчей: вызови get_match_breakdown с фильтрами
- Для тренера: get_coach_info → get_team_stats
- Для команды: get_team_stats
- search_web_context — только для фактов (роль, тактика, тренер)
НЕ отвечай без данных. Вызови инструмент.

ПРИОРИТЕТ ДАННЫХ:
- SofaScore — ОСНОВНОЙ: оборона, дриблинг, единоборства, пасы, удары. Данные ПО КАЖДОМУ ТУРНИРУ отдельно.
- Understat — ДОПОЛНЕНИЕ: xGChain, xGBuildup (продвижение мяча), поматчевая разбивка по соперникам.

РЕЙТИНГИ АГРЕГАТОРОВ (SofaScore rating) — НЕ ИСТИНА:
- Рейтинг SofaScore — это автоматическая оценка алгоритма, НЕ экспертная. Он часто ангажирован и неточен.
- НИКОГДА не используй рейтинг агрегатора как доказательство качества игры. Не пиши "рейтинг 7.99 — отлично".
- Можешь УПОМЯНУТЬ рейтинг в заголовке как справку, но АНАЛИЗ строй ТОЛЬКО на объективных метриках (голы, xG, отборы, пасы и т.д.).
- Если метрики хорошие но рейтинг низкий — рейтинг неправ. Если метрики плохие но рейтинг высокий — рейтинг неправ.

ОБЪЕКТИВНОСТЬ:
- Анализ строится ИСКЛЮЧИТЕЛЬНО на числовых данных из инструментов.
- [WEB CONTEXT] — ТОЛЬКО факты (клуб, позиция, роль, тренер). ИГНОРИРУЙ оценки журналистов, рейтинги, хвалебные/критические заголовки, медийный хайп.
- Репутация НЕ влияет на оценку. Одинаковые числа = одинаковый вывод.

ОСНОВНЫЕ ПРАВИЛА:
- Используй только данные из входного текста. Никаких внешних знаний (возраст, репутация, травмы).
- Числа не менять. Per90 не пересчитывать: использовать как данное из текста.
- Не добавляй метрики, которых нет в данных.
- Можно посчитать 2-3 простых производных: % ударов в створ, xG/удар, Голы−xG, Ассисты−xA.
- Внутренние ориентиры по позициям: говори "высоко/средне/низко для его роли", НЕ показывай числа ориентиров, НЕ говори "эталон/бенчмарк".

ПРИОРИТЕТЫ АНАЛИЗА ПО ПОЗИЦИЯМ (определи позицию → расставь приоритеты):

ЦЕНТРАЛЬНЫЙ ЗАЩИТНИК (DC):
  КЛЮЧЕВЫЕ МЕТРИКИ (подробно): отборы (кол-во, % выигранных), перехваты, выносы, блоки, воздушные единоборства (%, кол-во — критично), ошибки→гол/удар (красный флаг), пасы (точность, длинные — билдап из глубины), наземные единоборства (%), возвраты мяча, дисциплина.
  БОНУС (кратко если выделяется): голы, xGBuildup.
  ЗАПРЕЩЕНО: НЕ анализируй xG, удары, big chances, голевую частоту, xA, ключевые пасы. Если ЦЗ забил 2+ голов — 1 строка бонус. Если 0-1 — не упоминай.

ФЛАНГОВЫЙ ЗАЩИТНИК (DR, DL):
  КЛЮЧЕВЫЕ: отборы, перехваты, единоборства (оборона), кроссы (кол-во, точность! — ключевое для фланга), пасы в финальную треть/на чужой половине, дриблинг (успешность — продвижение по флангу), xA, ассисты.
  БОНУС: голы, xGBuildup. НЕ КЛЮЧЕВОЕ: xG, удары из штрафной, big chances missed.

ОПОРНЫЙ ПОЛУЗАЩИТНИК (DM):
  КЛЮЧЕВЫЕ: отборы (кол-во, %), перехваты, возвраты мяча — основа роли. Пасы (точность, длинные — диспетчерская функция). Единоборства (наземные, воздушные). xGBuildup — вовлечённость в розыгрыш. Ошибки→гол/удар. Дисциплина.
  БОНУС: ассисты, xA. НЕ КЛЮЧЕВОЕ: голы, xG, удары, дриблинг.

ЦЕНТРАЛЬНЫЙ ПОЛУЗАЩИТНИК (MC):
  КЛЮЧЕВЫЕ: пасы (точность, финальная треть, ключевые передачи), xGBuildup/xGChain — двигатель ли он игры. Отборы, перехваты — оборонительный вклад. Единоборства. xA, ассисты.
  УМЕРЕННО: голы, xG (зависит от роли: box-to-box vs глубокий).

ВИНГЕР / КРАЙНИЙ ПЗ (AML, AMR, ML, MR):
  КЛЮЧЕВЫЕ: дриблинг (успешность %, потери — главный навык). Кроссы (точность), ключевые передачи. xA, ассисты, big chances created. xG, голы, удары — голевая угроза. Пасы на чужой половине/в финальную треть.
  БОНУС: прессинг (отборы в атак. трети). НЕ КЛЮЧЕВОЕ: выносы, перехваты, воздушные единоборства.

АТАКУЮЩИЙ ПЗ (AM, CAM):
  КЛЮЧЕВЫЕ: xA, ассисты, ключевые передачи, big chances created — креатив. xGChain — вовлечённость в голевые атаки. Голы, xG, удары. Дриблинг, пасы в финальную треть.
  НЕ КЛЮЧЕВОЕ: выносы, перехваты, длинные передачи.

НАПАДАЮЩИЙ (F, FW, FC, S):
  КЛЮЧЕВЫЕ: голы, xG, реализация (Голы−xG) — основа. Удары (из штрафной vs из-за, xG/удар). Big chances missed. Частота голов (scoringFrequency). xA, ассисты. Воздушные единоборства. Офсайды, штанги.
  БОНУС: прессинг (отборы в атак. трети). НЕ КЛЮЧЕВОЕ: выносы, перехваты, точность пасов, длинные передачи.

ВРАТАРЬ (GK):
  КЛЮЧЕВЫЕ: сейвы (кол-во, поймано/отбито), пропущенные (из штрафной/издалека), сухие матчи, ошибки→гол (критично), пасы (точность, длинные — розыгрыш от ворот), отбитые пенальти.
  ЗАПРЕЩЕНО: xG, удары, голы, ассисты, дриблинг, единоборства наземные.

ТАКТИЧЕСКИЙ КОНТЕКСТ (из [WEB CONTEXT]):
- Используй для понимания РОЛИ игрока (box-to-box, опорник, плеймейкер, инвертированный вингер).
- Учитывай СТИЛЬ КОМАНДЫ (прессинг, контратаки, владение) при оценке метрик.
- Ключевой/ротационный игрок — это влияет на интерпретацию минут и статистики.
- НЕ копируй текст контекста дословно. Интегрируй естественно.

СТРУКТУРА ОТВЕТА ДЛЯ ОДНОГО ИГРОКА:

1) Заголовок одной строкой:
   Имя (Клуб) — позиция | сезон | минут: N | рейтинг: R

2) Сезон в цифрах (2-3 строки):
   - Матчи/голы/ассисты по ВСЕМ турнирам (лига + ЛЧ + кубки, указать каждый)
   - xG, xA, Голы−xG, Ассисты−xA

3) Ключевые выводы (4-6 нумерованных пунктов):
   Каждый пункт = ЗАГОЛОВОК (яркое описание) + конкретные цифры + вывод для позиции.
   Пиши как аналитик: "259 возвратов мяча — один из лучших показателей. 90 отборов (62.2% выигранных)..."
   НЕ как робот: "Отборы: 90, Перехваты: 34".
   Цитируй конкретные числа, проценты, per90 из данных. Привязывай к позиции и контексту команды.
   Учитывай позицию команды в таблице: игрок из андердога оценивается иначе, чем из лидера.

4) Кубки и еврокубки (ОБЯЗАТЕЛЬНЫЙ блок если данные есть):
   Отдельный блок: сравни объективные метрики (голы, xG, отборы, пасы) в лиге vs ЛЧ/ЛЕ/кубках.
   ВАЖНО О СОПЕРНИКАХ В КУБКАХ:
   - НЕ выделяй голы/ассисты против слабых клубов (Копенгаген, Мидтъюлланд, Шахтёр и т.п.) как достижение.
   - "Выдающийся матч" = только против топ-клубов (Реал, Барса, Баварии, ПСЖ, Ман Сити и т.п.) или в решающих стадиях (полуфинал, финал).
   - Голы против слабых соперников в групповой стадии — это ОЖИДАЕМО, не "выдающееся выступление".
   - Оценивай: показывает ли себя в ПЛЕЙ-ОФФ и против СИЛЬНЫХ? Или "набивает" в группе на слабых?

5) Проверка на прочность (ОБЯЗАТЕЛЬНЫЙ блок — никогда не пропускай!):
   а) ПО СОПЕРНИКАМ: используй разбивку по соперникам + таблицу лиги.
      - Нападающий: против каких команд голы/ассисты? Топ-клубы или аутсайдеры? "Набивает стату"?
      - Полузащитник: минуты против топов = доверие тренера. ЗАПРЕЩЕНО критиковать за 0 голов.
      - Защитник: играл ли полные матчи против топов? Результат команды. ЗАПРЕЩЕНО критиковать за 0 голов.
      - Если "[НЕ ИГРАЛ]"/0 мин — НЕ минус, нет данных. Если команда-андердог — 0 голов против Ливерпуля = НОРМАЛЬНО.
      - Конкретные примеры с именами соперников и цифрами.
   б) ПО ТУРНИРАМ (SofaScore агрегаты): рейтинг/голы/единоборства в лиге vs ЛЧ vs кубки.

6) Неожиданный плюс для позиции (0-2 пункта):
   Что не типично для этой роли, но выделяется (вратарь с высокой точностью пасов, защитник с высоким xA).

7) Риски / что настораживает (1-3 пункта):
   Малая выборка, низкие ключевые метрики, дисциплина, потери при дриблинге, ошибки→удар.
   ДРИБЛИНГ В КОНТЕКСТЕ: много обводок + много потерь = рискованный стиль. xGBuildup показывает полезность.

8) ОЦЕНКА СЕЗОНА: X.XX/10 — одно предложение.
   Оценка ОБЯЗАТЕЛЬНО десятичная с двумя знаками (7.43/10, 8.91/10, 5.20/10). НЕ округляй.

СТРУКТУРА ДЛЯ СРАВНЕНИЙ:
1) Заголовок: Имя1 vs Имя2 — позиции, клубы, сезон
2) Сводная таблица метрик (8-12 штук): метрика | Игрок1 | Игрок2 | лучший
3) Преимущества КАЖДОГО игрока (2-4 пункта с цифрами)
4) Проверка на прочность: кто набирает стату на слабых, а кто и против топов
5) Кубки/еврокубки: кто сильнее на большой сцене
6) Итоговый рейтинг от лучшего к худшему с X.XX/10 и обоснованием

СТРУКТУРА ДЛЯ МАТЧЕЙ:
1) Заголовок: Имя — матч (счёт) | турнир | минуты | рейтинг
2) Контекст результата (1 строка)
3) Что сделал хорошо (2-3 пункта). Что не получилось (1-3 пункта).
4) Ключевые цифры
5) Вердикт X.XX/10 — может отличаться от SofaScore с объяснением

СТРУКТУРА ДЛЯ ТРЕНЕРОВ/КОМАНД:
1) Заголовок: тренер, клуб, ПЕРИОД ОЦЕНКИ (точные даты!), кол-во матчей
2) Результативность: PPG, позиция, win rate, xGD, перевыполнение/недобор xG
3) Тактический стиль: PPDA (<8 агрессивный, 8-11 умеренный, >11 низкий), deep completions, владение
4) Атака: xG/матч, big chances, откуда голы (фланги vs центр)
5) Оборона: xGA/матч, clean sheets, ошибки→гол
6) Форма: последние 5 матчей, тренд
7) Вердикт X.XX/10

ОБЪЁМ ТЕКСТА (важно для Telegram):
- Одиночный анализ: 25-45 строк. Это "читабельная карточка", не лекция и не отписка.
- Сравнение: 30-50 строк.
- Выбери 6-9 ключевых метрик — по ним дай пояснение+вывод. Остальные перечисли кратко.
- ЯЗЫК: русский. xG/xA оставляй аббревиатурами.
- НЕ используй слова "промпт", "эталон", "бенчмарк", "система", "инструмент".
"""

# ── Tool registry ────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    "resolve_player": {
        "fn": resolve_player,
        "description": (
            "Resolve a player name to their ID, team, league, and position. "
            "Useful to check if a player exists before fetching stats."
        ),
        "parameters": {
            "player_name": {"type": "string", "description": "Player name (any language, will be transliterated)"},
            "team_hint": {"type": "string", "description": "Optional team name to disambiguate", "default": ""},
        },
    },
    "get_player_stats": {
        "fn": get_player_stats,
        "description": (
            "Get full season statistics for a player: goals, xG, xA, assists, minutes, "
            "per-opponent breakdown, SofaScore details (dribbling, duels, rating), "
            "cup/european matches, and league standings. This is the main tool for player analysis."
        ),
        "parameters": {
            "player_name": {"type": "string", "description": "Player name (any language)"},
            "team_hint": {"type": "string", "description": "Team name hint for disambiguation", "default": ""},
            "season_year": {"type": "string", "description": "Season start year e.g. '2024'. Empty = current season", "default": ""},
        },
    },
    "get_match_breakdown": {
        "fn": get_match_breakdown,
        "description": (
            "Get per-match stats for a player from SofaScore. Use for 'how did X play against Y', "
            "'last match', 'last 5 matches', 'performance in Champions League'. "
            "Returns detailed per-match stats: goals, xG, passes, tackles, rating etc."
        ),
        "parameters": {
            "player_name": {"type": "string", "description": "Player name"},
            "team_hint": {"type": "string", "description": "Team hint", "default": ""},
            "opponent": {"type": "string", "description": "Filter by opponent team name (English)", "default": ""},
            "tournament": {"type": "string", "description": "Filter by tournament name", "default": ""},
            "count": {"type": "integer", "description": "Number of recent matches to return. 0 = all", "default": 0},
            "all_time": {"type": "boolean", "description": "If true, search all available history not just current season", "default": False},
        },
    },
    "get_team_stats": {
        "fn": get_team_stats,
        "description": (
            "Get team season statistics: xG, xGA, PPG, form, wins/draws/losses, pressing metrics (PPDA). "
            "For coach evaluation, pass coach_name and date range to filter by tenure."
        ),
        "parameters": {
            "team_name": {"type": "string", "description": "Team name in English"},
            "league": {"type": "string", "description": "League: Premier League, LaLiga, Serie A, Bundesliga, Ligue 1, Russian Premier League"},
            "coach_name": {"type": "string", "description": "Coach name to filter by their tenure", "default": ""},
            "coach_since": {"type": "string", "description": "Start date YYYY-MM-DD for coach tenure", "default": ""},
            "coach_until": {"type": "string", "description": "End date YYYY-MM-DD for coach tenure (empty = current)", "default": ""},
        },
    },
    "get_coach_info": {
        "fn": get_coach_info,
        "description": (
            "Search for coach information: current team, appointment date, league. "
            "Use to find out who coaches a team or when a coach started."
        ),
        "parameters": {
            "coach_name": {"type": "string", "description": "Coach name or team name to search"},
        },
    },
    "get_league_standings": {
        "fn": get_league_standings,
        "description": "Get top-10 league standings table. Use to assess team position or opponent strength.",
        "parameters": {
            "league": {"type": "string", "description": "League name: EPL, La_Liga, Serie_A, Bundesliga, Ligue_1, RFPL"},
            "season_year": {"type": "string", "description": "Season year, default current", "default": ""},
        },
    },
    "search_web_context": {
        "fn": search_web_context,
        "description": (
            "Search the web for tactical context about a player, team, or coach. "
            "Returns current info: playing style, role in team, recent form, transfers. "
            "Use when you need context not available from stats tools."
        ),
        "parameters": {
            "query": {"type": "string", "description": "Search query in English"},
        },
    },
}

# ── Schema builder ───────────────────────────────────────────────────


def _build_tool_schemas(tool_names: list[str]) -> list[dict[str, Any]]:
    """Build OpenRouter-compatible JSON schemas from TOOL_REGISTRY."""
    schemas = []
    for name in tool_names:
        tool_def = TOOL_REGISTRY.get(name)
        if not tool_def:
            continue
        params = tool_def.get("parameters", {})
        properties = {}
        required = []
        for param_name, param_info in params.items():
            prop: dict[str, Any] = {
                "type": param_info.get("type", "string"),
                "description": param_info.get("description", ""),
            }
            if "default" in param_info:
                prop["default"] = param_info["default"]
            else:
                required.append(param_name)
            properties[param_name] = prop
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        schemas.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool_def["description"],
                "parameters": schema,
            },
        })
    return schemas


MAX_TOOL_RESULT_CHARS = 12000  # Limit tool output to avoid context overflow


def _serialize_tool_result(result: Any) -> str:
    """Serialize tool result to text for the agent."""
    if result is None:
        return "No data"
    if isinstance(result, str):
        text = result
    elif isinstance(result, list):
        if not result:
            return "Empty list"
        items = []
        for i, item in enumerate(result, 1):
            items.append(f"[{i}] {item}")
        text = "\n".join(items)
    else:
        text = str(result)

    # Truncate if too long
    if len(text) > MAX_TOOL_RESULT_CHARS:
        text = text[:MAX_TOOL_RESULT_CHARS] + "\n\n[... truncated, data too large ...]"
    return text


# ── Pre-search ───────────────────────────────────────────────────────


def _is_simple_query(query: str) -> bool:
    """Check if query is simple enough for direct Sonar search."""
    words = query.strip().split()
    if len(words) <= 2 and all(ord(c) < 128 or c == ' ' for c in query):
        return True
    return False


async def _pre_search(user_query: str, llm: LLMClient) -> str:
    """Mandatory web search before orchestration for up-to-date context."""
    try:
        if _is_simple_query(user_query):
            search_query = f"{user_query} football player 2025 stats team"
        else:
            search_query = await llm.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        "Rewrite as a brief English web search query for football stats. "
                        f"User query: {user_query}\n"
                        "Reply ONLY with the search query, nothing else."
                    ),
                }],
                model_type="light",
                temperature=0.1,
                max_tokens=100,
            )
            search_query = search_query.strip().strip('"').strip("'")

        logger.info("Pre-search query: %s", search_query)

        result = await llm.chat(
            messages=[{"role": "user", "content": (
                f"{search_query}\n\n"
                "Reply with FACTS ONLY: current club, position, tactical role, manager, "
                "formation, recent transfers, injury status. "
                "DO NOT include: journalist opinions, ratings, awards, 'best/worst' judgments, "
                "media narratives, aggregator scores, or any subjective assessments."
            )}],
            model_type="search",
            temperature=0.3,
            max_tokens=2000,
        )
        return result
    except Exception as e:
        logger.warning("Pre-search failed: %s", e)
        return ""


# ── Agentic loop ─────────────────────────────────────────────────────


async def execute_query(
    user_query: str,
    llm: LLMClient,
    clients: dict[str, Any],
) -> str:
    """Main orchestrator: pre-search + agentic tool-calling loop."""

    # 1. Mandatory pre-search
    web_context = await _pre_search(user_query, llm)

    # 2. Build system prompt with web context
    system_content = SYSTEM_PROMPT
    if web_context:
        system_content += f"\n\n[WEB CONTEXT]\n{web_context}"

    # 3. Build messages
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_query},
    ]

    # 4. Build tool schemas
    tool_schemas = _build_tool_schemas(list(TOOL_REGISTRY.keys()))

    # 5. Agentic loop
    called_tools: list[str] = []
    seen_calls: set[str] = set()  # track (fn_name, args_hash) to detect loops
    for iteration in range(MAX_ITERATIONS):
        # On last 2 iterations, stop offering tools to force a final answer
        current_tools = tool_schemas if iteration < MAX_ITERATIONS - 2 else []

        logger.info("Orchestrator iteration %d/%d, tools called so far: %s",
                     iteration + 1, MAX_ITERATIONS, called_tools)

        response = await llm.chat_with_tools(
            messages=messages,
            tools=current_tools,
            model_type="heavy",
            temperature=0.6,
        )

        # Log what we got back
        has_content = bool(response.get("content"))
        has_tools = bool(response.get("tool_calls"))
        logger.info("Iteration %d response: content=%s, tool_calls=%s",
                     iteration + 1, len(response["content"]) if response.get("content") else 0,
                     len(response["tool_calls"]) if response.get("tool_calls") else 0)

        # No tool_calls → final answer
        if not has_tools:
            content = response.get("content", "")
            if not content:
                # Empty response — force a text-only completion
                logger.warning("Empty response at iteration %d, forcing text completion", iteration + 1)
                messages.append({"role": "user", "content": "Now write your final analysis based on the data above. No more tool calls."})
                continue
            logger.info(
                "Orchestrator done in %d iterations, tools called: %s",
                iteration + 1, called_tools,
            )
            return content

        # Has tool_calls → execute them
        messages.append({
            "role": "assistant",
            "content": response.get("content"),
            "tool_calls": response["tool_calls"],
        })

        for tool_call in response["tool_calls"]:
            fn_name = tool_call["function"]["name"]
            fn_args_raw = tool_call["function"].get("arguments", "{}")

            try:
                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
            except json.JSONDecodeError:
                fn_args = {}

            # Detect duplicate calls (same tool + same args)
            call_sig = f"{fn_name}:{json.dumps(fn_args, sort_keys=True)}"
            if call_sig in seen_calls:
                logger.warning("Duplicate tool call detected: %s, returning cached hint", fn_name)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": "You already called this tool with the same arguments. Use the data you already have.",
                })
                continue

            seen_calls.add(call_sig)
            called_tools.append(fn_name)

            logger.info("Executing tool: %s(%s)", fn_name, fn_args)
            tool_result = await _execute_tool(fn_name, fn_args, clients)
            logger.info("Tool %s returned %d chars", fn_name, len(tool_result))

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": tool_result,
            })

    # If we exhausted iterations, try one last text-only call
    logger.warning("Orchestrator exceeded %d iterations, forcing final answer", MAX_ITERATIONS)
    messages.append({"role": "user", "content": "Write your final analysis NOW based on all the data you have collected. Do not call any more tools."})
    try:
        response = await llm.chat_with_tools(
            messages=messages,
            tools=[],  # no tools — force text
            model_type="heavy",
            temperature=0.6,
        )
        content = response.get("content", "")
        if content:
            return content
    except Exception:
        logger.exception("Final forced completion failed")

    return "Не удалось сформировать ответ. Попробуй переформулировать запрос."


async def _execute_tool(
    fn_name: str,
    fn_args: dict[str, Any],
    clients: dict[str, Any],
) -> str:
    """Execute a tool and return serialized result."""
    tool_def = TOOL_REGISTRY.get(fn_name)
    if not tool_def:
        return f"Error: tool '{fn_name}' not found"

    fn = tool_def["fn"]
    try:
        # All tools take clients as kwarg + their own params
        result = await fn(clients=clients, **fn_args)
        return _serialize_tool_result(result)
    except Exception as e:
        logger.error("Tool execution error %s(%s): %s", fn_name, fn_args, e, exc_info=True)
        return f"Error: {e}"
