"""Web search tools for the orchestrator — limited to date lookups only."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def search_web_context(query: str, clients: dict[str, Any]) -> str:
    """Search the web ONLY for coach appointment/dismissal dates or player transfer dates."""
    llm = clients["llm"]
    result = await llm.chat(
        messages=[{"role": "user", "content": (
            f"{query}\n\n"
            "Reply with DATES and FACTS ONLY: appointment date, dismissal date, "
            "transfer date, signing date. "
            "DO NOT include: tactical analysis, playing style, form, journalist opinions, "
            "ratings, awards, media narratives, or any subjective assessments. "
            "If the query is not about coach dates or transfer dates, reply: "
            "'This tool is only for coach/transfer date lookups.'"
        )}],
        model_type="search",
        temperature=0.3,
        max_tokens=500,
    )
    return result or "No results found."
