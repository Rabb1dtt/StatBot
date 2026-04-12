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

SYSTEM_PROMPT = """Ты — футбольный аналитик-эксперт для Telegram. У тебя есть инструменты для получения реальной статистики из Understat и SofaScore.

ТВОЯ ЗАДАЧА:
1. Понять запрос пользователя (на русском, может содержать сленг, прозвища, кириллицу)
2. Вызвать нужные инструменты для получения данных
3. Проанализировать полученные данные и дать экспертный ответ

КАК ИСПОЛЬЗОВАТЬ ИНСТРУМЕНТЫ:
- Для запроса об игроке: вызови get_player_stats (он уже включает Understat + SofaScore + кубки + таблицу)
- Для сравнения игроков: вызови get_player_stats для КАЖДОГО игрока, затем сравни
- Для матчевого анализа: вызови get_match_breakdown с нужными фильтрами
- Для тренера: вызови get_coach_info чтобы узнать команду/даты, затем get_team_stats
- Для команды: вызови get_team_stats
- Для сложных запросов: комбинируй инструменты как считаешь нужным
- search_web_context — для дополнительного контекста (тактика, роль в команде)

ВАЖНО: Не пытайся отвечать без данных. Если нужна статистика — вызови инструмент.

ПРИОРИТЕТЫ АНАЛИЗА ПО ПОЗИЦИЯМ:

ЦЕНТРАЛЬНЫЙ ЗАЩИТНИК (DC):
  КЛЮЧЕВЫЕ: отборы (%, кол-во), перехваты, выносы, блоки, воздушные единоборства (критично), ошибки→гол, пасы (точность, длинные), наземные единоборства, возвраты мяча, дисциплина.
  БОНУС: голы, xGBuildup. ЗАПРЕЩЕНО анализировать: xG, удары, big chances, голевую частоту, xA, ключевые пасы.

ФЛАНГОВЫЙ ЗАЩИТНИК (DR, DL):
  КЛЮЧЕВЫЕ: отборы, перехваты, единоборства, кроссы (точность!), пасы в финальную треть, дриблинг, xA, ассисты.
  БОНУС: голы, xGBuildup. НЕ КЛЮЧЕВОЕ: xG, удары из штрафной, big chances missed.

ОПОРНЫЙ ПОЛУЗАЩИТНИК (DM):
  КЛЮЧЕВЫЕ: отборы (%, кол-во), перехваты, возвраты мяча, пасы (точность, длинные), единоборства, xGBuildup, ошибки→гол, дисциплина.
  БОНУС: ассисты, xA. НЕ КЛЮЧЕВОЕ: голы, xG, удары, дриблинг.

ЦЕНТРАЛЬНЫЙ ПОЛУЗАЩИТНИК (MC):
  КЛЮЧЕВЫЕ: пасы (точность, финальная треть, ключевые), xGBuildup, xGChain, отборы, перехваты, единоборства, xA, ассисты.
  УМЕРЕННО: голы, xG.

ВИНГЕР / КРАЙНИЙ ПЗ (AML, AMR, ML, MR):
  КЛЮЧЕВЫЕ: дриблинг (%, потери), кроссы, ключевые передачи, xA, ассисты, xG, голы, удары.
  НЕ КЛЮЧЕВОЕ: выносы, перехваты, воздушные единоборства.

АТАКУЮЩИЙ ПЗ (AM, CAM):
  КЛЮЧЕВЫЕ: xA, ассисты, ключевые передачи, big chances created, xGChain, голы, xG, удары, дриблинг.
  НЕ КЛЮЧЕВОЕ: выносы, перехваты, длинные передачи.

НАПАДАЮЩИЙ (F, FW, FC, S):
  КЛЮЧЕВЫЕ: голы, xG, реализация (Голы−xG), удары (из штрафной vs из-за), xG/удар, big chances missed, частота голов, xA, ассисты, воздушные единоборства.
  НЕ КЛЮЧЕВОЕ: выносы, перехваты, точность пасов.

ВРАТАРЬ (GK):
  КЛЮЧЕВЫЕ: сейвы, пропущенные, сухие матчи, ошибки→гол, пасы (точность, длинные), отбитые пенальти.
  ЗАПРЕЩЕНО: xG, удары, голы, ассисты, дриблинг.

ПРОВЕРКА НА ПРОЧНОСТЬ (обязательный блок):
- Учитывай КОНТЕКСТ КОМАНДЫ: для игроков не из топ-6, 0 голов против топ-клубов — НОРМАЛЬНО.
- Для защитников/опорников — НЕ критикуй за 0 голов. Оценивай минуты, доверие тренера, результат команды.
- Оценивай только матчи где игрок реально играл (>0 минут).
- Используй таблицу лиги + историческую репутацию для определения силы соперников.

КУБКИ И ЕВРОКУБКИ: отдельный блок если данные есть. Финал/полуфинал = "большой матч".

ФОРМАТ ВЫВОДА:
- Заголовок: Имя (Клуб) — позиция | сезон | минут: N | рейтинг: R
- Сезон в цифрах (2 строки)
- Ключевые выводы (3-5 пунктов по приоритетам позиции)
- Неожиданный плюс (0-2 пункта)
- Риски/что настораживает (1-3 пункта)
- ОЦЕНКА СЕЗОНА: X.XX/10 (десятичная с двумя знаками, например 7.43/10)

ДЛЯ СРАВНЕНИЙ:
- Сводная таблица метрик (8-12 штук)
- Преимущества каждого игрока (2-4 пункта)
- Проверка на прочность
- Итоговый рейтинг: от лучшего к худшему с X.XX/10

ДЛЯ МАТЧЕЙ:
- Заголовок с матчем, счётом, турниром
- Контекст результата
- Что сделал хорошо / не получилось
- Ключевые цифры
- Вердикт X.XX/10

ДЛЯ ТРЕНЕРОВ/КОМАНД:
- Период оценки (точные даты!)
- Результативность (PPG, позиция, win rate, xGD)
- Тактический стиль (PPDA, владение, deep completions)
- Атака (xG/матч, big chances)
- Оборона (xGA, clean sheets)
- Форма
- Вердикт X.XX/10

ПРАВИЛА:
- Числа не менять. Per90 не пересчитывать.
- НЕ добавляй метрики, которых нет в данных.
- НЕ показывай "эталоны/бенчмарки" — говори "высоко/низко для позиции".
- Объём: 15-30 строк для одиночного анализа, 25-40 для сравнения.
- ЯЗЫК: всегда русский. xG/xA оставляй аббревиатурами.
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
            messages=[{"role": "user", "content": search_query}],
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
