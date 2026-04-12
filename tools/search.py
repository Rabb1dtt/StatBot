"""Web search tools for the orchestrator."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def search_web_context(query: str, clients: dict[str, Any]) -> str:
    """Search the web for tactical context about a player/team via Perplexity Sonar."""
    llm = clients["llm"]
    result = await llm.chat(
        messages=[{"role": "user", "content": (
            f"{query}\n\n"
            "Reply with FACTS ONLY: current club, position, tactical role, manager, "
            "formation, playing style, recent transfers, injury status. "
            "DO NOT include: journalist opinions, ratings, awards, 'best/worst' judgments, "
            "media narratives, aggregator scores, or any subjective assessments."
        )}],
        model_type="search",
        temperature=0.3,
        max_tokens=2000,
    )
    return result or "No results found."
