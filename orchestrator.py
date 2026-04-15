"""AI orchestrator: skill router, TOOL_REGISTRY, pre-search, agentic loop."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from llm_client import LLMClient
from tools.player import resolve_player, get_player_stats, get_match_breakdown
from tools.team import get_team_stats, get_coach_info
from tools.league import get_league_standings
from tools.search import search_web_context

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 10

SKILLS_PATH = Path(__file__).parent / "skills.md"
BENCHMARKS_PATH = Path(__file__).parent / "benchmarks.md"
DEFAULT_SKILL = "player_analysis"

_BENCHMARKS_CACHE: str | None = None


def _load_benchmarks() -> str:
    """Load full benchmarks.md text (injected into heavy-model system prompt)."""
    global _BENCHMARKS_CACHE
    if _BENCHMARKS_CACHE is not None:
        return _BENCHMARKS_CACHE
    if not BENCHMARKS_PATH.exists():
        logger.warning("benchmarks.md not found at %s", BENCHMARKS_PATH)
        _BENCHMARKS_CACHE = ""
        return ""
    _BENCHMARKS_CACHE = BENCHMARKS_PATH.read_text(encoding="utf-8")
    logger.info("Loaded benchmarks.md: %d chars", len(_BENCHMARKS_CACHE))
    return _BENCHMARKS_CACHE

# ── Common prompt (shared across all skills) ─────────────────────────

COMMON_PROMPT = """Ты — футбольный аналитик-эксперт для Telegram. У тебя есть инструменты для получения реальной статистики из Understat и SofaScore. На выходе — ОДИН удобочитаемый текст, без тех.терминов про "промт/эталоны/перевод", без "derived".

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

НЕЗАВИСИМЫЙ АНАЛИЗ. РЕЙТИНГИ АГРЕГАТОРОВ — НЕ ИСТИНА:
- Твоя задача — проводить НЕЗАВИСИМЫЙ аналитический разбор. ИГНОРИРУЙ рейтинги и оценки агрегаторов (SofaScore, WhoScored, FotMob и т.п.), которые часто бывают проплачены, ангажированы или искажены алгоритмом.
- НИКОГДА не используй рейтинг агрегатора как доказательство качества игры. Не пиши "рейтинг 7.99 — отлично", "по версии SofaScore — лучший", "высокая оценка = хорошо сыграл".
- Рейтинг можно УПОМЯНУТЬ в заголовке как нейтральную справку одной цифрой, но НИ ОДИН вывод, плюс или минус в анализе не должен на него опираться.
- Если метрики хорошие, а рейтинг низкий — игнорируй рейтинг. Если метрики плохие, а рейтинг высокий — игнорируй рейтинг. Твой вывод строится на числах (голы, xG, отборы, пасы, %дуэлей, эталоны ниже), а не на чужой оценке.
- То же касается медийных оценок ("лучший игрок тура", "разочарование сезона"): это шум, не данные.

ОБЪЕКТИВНОСТЬ:
- Анализ строится ИСКЛЮЧИТЕЛЬНО на числовых данных из инструментов.
- [WEB CONTEXT] — ТОЛЬКО факты (клуб, позиция, роль, тренер). ИГНОРИРУЙ оценки журналистов, рейтинги, хвалебные/критические заголовки, медийный хайп.
- Репутация НЕ влияет на оценку. Одинаковые числа = одинаковый вывод.
- ВОЗРАСТ НЕ ВЛИЯЕТ НА ОЦЕНКУ. НЕ пиши "для 18-летнего это феноменально" или "для ветерана хорошо". Игрок оценивается по цифрам ОТНОСИТЕЛЬНО ВСЕХ игроков на той же позиции, независимо от возраста. 18-летний с xG 5.0 и 30-летний с xG 5.0 — одинаковая оценка. Возраст — это контекст из внешних знаний, а не из данных.

ОСНОВНЫЕ ПРАВИЛА:
- Используй только данные из входного текста. Никаких внешних знаний (возраст, репутация, травмы).
- Числа не менять. Per90 не пересчитывать: использовать как данное из текста.
- Не добавляй метрики, которых нет в данных.
- Можно посчитать 2-3 простых производных: % ударов в створ, xG/удар, Голы−xG, Ассисты−xA.
- ЭТАЛОНЫ: в блоке [БЕНЧМАРКИ] ниже — числовые ориентиры по позициям (per 90, медиана топ-25%). СРАВНИВАЙ реальные числа игрока с эталоном явно: "Аэрия 62% (эталон ЦЗ ≥60%) — на уровне топ-25%", "xG 0.28 при эталоне страйкера ≥0.40 — ниже нормы". Не скрывай эталоны.
- Учитывай ВЕСА блоков (🔴 ключевые 35–40% / 🟠 важные 25–30% / 🟡 средние 20–25% / 🟢 низкие 10–15%): слабость в ключевых бьёт по оценке сильнее, чем в низких.

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

РОЛЬ ≠ ПОЗИЦИЯ (КРИТИЧНО):
- Формальная позиция (MC, AM, AMR и т.п.) из данных — только стартовая точка. Реальная РОЛЬ в команде может отличаться: номинальный MC играет как опорник, номинальный AM оттянут в глубину, AMR — инвертированный вингер, CF — ложная девятка, FB — инвертированный латераль с заходом в центр.
- ОБЯЗАТЕЛЬНО сверяйся с [WEB CONTEXT]: какую функцию игрок реально выполняет (плеймейкер/разрушитель/финишёр/билдап-защитник), какие задачи ставит тренер.
- Если роль отличается от позиции — оценивай по ЭТАЛОНАМ ФАКТИЧЕСКОЙ РОЛИ, не по номинальной. Пример: номинальный MR, но реально играет как AM → используй эталоны AM.
- Это важно и для выбора метрик: ЦЗ-билдапер оценивается с бОльшим весом на прогрессивные пасы, инвертированный латераль — с весом на ключевые передачи в центре, а не кроссы.

ТАКТИЧЕСКИЙ КОНТЕКСТ:
- Стиль команды (прессинг, контратаки, владение) корректирует интерпретацию: xA и progressive passes в команде владения выше по умолчанию, в команде контратак — ниже.
- Ключевой vs ротационный игрок — влияет на интерпретацию минут.
- НЕ копируй [WEB CONTEXT] дословно. Интегрируй естественно.

ОБЩИЕ ТРЕБОВАНИЯ К ТЕКСТУ:
- ЯЗЫК: русский. xG/xA оставляй аббревиатурами.
- НЕ используй слова "промпт", "система", "инструмент" (технический жаргон). Слова "эталон"/"бенчмарк" допустимы и ожидаются при ссылке на числовые ориентиры.
- Структура ответа определяется активным скиллом (см. блок [SKILL] ниже) — строго следуй ей.
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


# ── Skills loader & router ───────────────────────────────────────────

_SKILLS_CACHE: dict[str, dict[str, str]] | None = None


def _load_skills() -> dict[str, dict[str, str]]:
    """Parse skills.md into {name: {when, body}} where body is full skill block."""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is not None:
        return _SKILLS_CACHE

    if not SKILLS_PATH.exists():
        logger.warning("skills.md not found at %s", SKILLS_PATH)
        _SKILLS_CACHE = {}
        return _SKILLS_CACHE

    text = SKILLS_PATH.read_text(encoding="utf-8")
    skills: dict[str, dict[str, str]] = {}

    # Each skill is "## <name>\n...\n" until next "## " or EOF
    blocks = re.split(r"^## ", text, flags=re.MULTILINE)
    for block in blocks[1:]:  # first chunk is header/preamble
        lines = block.split("\n", 1)
        if len(lines) < 2:
            continue
        name = lines[0].strip()
        body = lines[1].strip()
        when_match = re.search(r"\*\*Когда:\*\*\s*(.+)", body)
        when = when_match.group(1).strip() if when_match else ""
        skills[name] = {"when": when, "body": body}

    logger.info("Loaded %d skills: %s", len(skills), list(skills.keys()))
    _SKILLS_CACHE = skills
    return skills


async def _route_to_skill(user_query: str, llm: LLMClient) -> str:
    """Pick ONE skill name for the query using a cheap router model."""
    skills = _load_skills()
    if not skills:
        return DEFAULT_SKILL

    catalog = "\n".join(f"- {name}: {s['when']}" for name, s in skills.items())
    system = (
        "Ты — роутер скиллов. Выбери РОВНО ОДИН скилл для запроса пользователя.\n"
        "Ответ: ТОЛЬКО имя скилла одним словом snake_case. Без пояснений, без кавычек, без точки.\n\n"
        f"Скиллы:\n{catalog}"
    )
    try:
        raw = await llm.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_query},
            ],
            model_type="router",
            temperature=0.0,
            max_tokens=10,
        )
    except Exception as e:
        logger.warning("Router call failed: %s — fallback to %s", e, DEFAULT_SKILL)
        return DEFAULT_SKILL

    # Extract first snake_case token that matches a known skill
    tokens = re.findall(r"[a-z_]+", raw.lower())
    for tok in tokens:
        if tok in skills:
            logger.info("Router picked skill: %s (raw=%r)", tok, raw.strip())
            return tok

    logger.warning("Router output %r did not match any skill — fallback to %s",
                   raw.strip(), DEFAULT_SKILL)
    return DEFAULT_SKILL


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
    """Main orchestrator: route to skill + pre-search + agentic tool-calling loop."""

    # 1. Route to a skill (cheap model, one-word output)
    skill_name = await _route_to_skill(user_query, llm)
    skills = _load_skills()
    skill = skills.get(skill_name) or skills.get(DEFAULT_SKILL) or {"body": ""}

    # 2. Mandatory pre-search
    web_context = await _pre_search(user_query, llm)

    # 3. Build system prompt: common rules + benchmarks + selected skill block + web context
    benchmarks = _load_benchmarks()
    system_content = COMMON_PROMPT
    if benchmarks:
        system_content += f"\n\n[БЕНЧМАРКИ — эталонные значения per 90 по позициям, используй для сравнения]\n{benchmarks}"
    system_content += f"\n\n[SKILL: {skill_name}]\n{skill['body']}"
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
