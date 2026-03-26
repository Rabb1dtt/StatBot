import asyncio
from dataclasses import dataclass
from typing import Optional

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

import config
from football_client import FootballClient


@dataclass
class ResolvedPlayer:
    player_id: int
    name: str
    team: Optional[str]
    position: Optional[str]


class NameResolver:
    def __init__(self, client: FootballClient) -> None:
        self.client = client
        if OpenAI and config.OPENROUTER_API_KEY:
            self._llm = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.OPENROUTER_API_KEY,
            )
        else:
            self._llm = None
        self.model = config.OPENROUTER_MODEL

    async def resolve(self, query: str) -> Optional[ResolvedPlayer]:
        """
        Resolve a user query to a player.
        Strategy:
        1. Ask LLM to extract latin player name + team name from query
        2. Search API-Football with team context (saves API calls)
        3. Fallback: search across top leagues without team
        """
        latin_name, team_hint = await self._extract_name_and_team(query)
        search_name = latin_name or query

        result = await self.client.search_player(search_name, team_name=team_hint)
        if not result:
            # Try original query if LLM gave a different name
            if latin_name and latin_name.lower() != query.lower():
                result = await self.client.search_player(query)
            if not result:
                return None

        player = result.get("player", {})
        stats = result.get("statistics", [])
        team_name = stats[0]["team"]["name"] if stats else None
        position = stats[0]["games"]["position"] if stats else None

        return ResolvedPlayer(
            player_id=player["id"],
            name=player.get("name", search_name),
            team=team_name,
            position=position,
        )

    async def _extract_name_and_team(self, query: str) -> tuple[Optional[str], Optional[str]]:
        """Use LLM to extract latin player name and team from a query."""
        if not self._llm:
            return None, None

        prompt = (
            "User is searching for a football player. Extract:\n"
            "1) Player name in Latin script (transliterate if needed)\n"
            "2) Team name in English (if mentioned or obvious)\n\n"
            "Reply EXACTLY in format:\n"
            "NAME: <player name>\n"
            "TEAM: <team name or UNKNOWN>\n\n"
            f"Query: {query}"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()

            text = await asyncio.to_thread(_call)
            name = None
            team = None
            for line in text.splitlines():
                if line.upper().startswith("NAME:"):
                    name = line.split(":", 1)[1].strip()
                elif line.upper().startswith("TEAM:"):
                    val = line.split(":", 1)[1].strip()
                    if val.upper() != "UNKNOWN":
                        team = val
            return name, team
        except Exception:
            return None, None
