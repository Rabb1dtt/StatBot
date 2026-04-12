import asyncio
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, List, Dict

import cyrtranslit
from rapidfuzz import fuzz, process

try:
    from openai import OpenAI
except Exception:
    OpenAI = None  # type: ignore

import config
from database import PlayerDB


@dataclass
class ResolvedPlayer:
    understat_id: int
    name: str
    team: str
    league: str
    position: str


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )


def _normalize(text: str) -> str:
    return _strip_accents(text).lower().strip()


def _transliterate(text: str) -> str:
    """Cyrillic to Latin."""
    return cyrtranslit.to_latin(text, "ru")


class NameResolver:
    def __init__(self, db: PlayerDB) -> None:
        self.db = db
        self._players: List[Dict] = []
        self._search_index: Dict[str, Dict] = {}  # name_search -> player dict
        if OpenAI and config.OPENROUTER_API_KEY:
            self._llm = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=config.OPENROUTER_API_KEY,
            )
        else:
            self._llm = None
        self.model_translate = config.MODEL_TRANSLATE
        self.model_orchestrator = config.MODEL_ORCHESTRATOR
        self.model_search = config.MODEL_SEARCH

    def rebuild_index(self) -> None:
        """Reload players from DB into memory for fast search."""
        self._players = self.db.get_all_players_for_search()
        self._search_index = {}
        for p in self._players:
            key = p["name_search"]
            if key not in self._search_index:
                self._search_index[key] = p

    def _fuzzy_search(self, query: str, limit: int = 5) -> List[Dict]:
        """Local fuzzy search across all players."""
        if not self._search_index:
            return []

        variants = set()
        variants.add(_normalize(query))
        variants.add(_normalize(_transliterate(query)))
        parts = query.strip().split()
        if len(parts) > 1:
            variants.add(_normalize(parts[-1]))
            variants.add(_normalize(_transliterate(parts[-1])))

        choices = list(self._search_index.keys())
        best_results: Dict[int, tuple] = {}

        for variant in variants:
            matches = process.extract(
                variant, choices, scorer=fuzz.WRatio, limit=limit
            )
            for name_key, score, _ in matches:
                player = self._search_index[name_key]
                uid = player["understat_id"]
                if uid not in best_results or score > best_results[uid][0]:
                    best_results[uid] = (score, player)

        sorted_results = sorted(best_results.values(), key=lambda x: x[0], reverse=True)
        return sorted_results[:limit]

    def _pick_best(
        self, results: List[tuple], team_hint: Optional[str] = None,
    ) -> Optional[tuple]:
        """Pick the best (score, player) result, boosting team_hint matches."""
        if not results:
            return None
        if not team_hint or len(results) == 1:
            return results[0]

        hint_lower = _normalize(team_hint)
        hint_latin = _normalize(_transliterate(team_hint))

        for score, player in results:
            team = _normalize(player.get("team", ""))
            if hint_lower in team or hint_latin in team or team in hint_lower or team in hint_latin:
                return (score, player)
        return results[0]

    def _to_resolved(self, score: float, player: Dict) -> ResolvedPlayer:
        return ResolvedPlayer(
            understat_id=player["understat_id"],
            name=player["name"],
            team=player.get("team", ""),
            league=player.get("league", ""),
            position=player.get("position", ""),
        )

    async def resolve(self, query: str, team_hint: Optional[str] = None) -> Optional[ResolvedPlayer]:
        """Resolve a player name query to a ResolvedPlayer."""
        MIN_SCORE = 55
        best = None

        # 1) LLM transliteration first
        if self._llm:
            guess = await self._guess_latin_name(query)
            if guess:
                llm_results = self._fuzzy_search(guess, limit=10)
                best = self._pick_best(llm_results, team_hint)

        # 2) Also try direct fuzzy on original query
        direct_results = self._fuzzy_search(query, limit=10)
        direct_best = self._pick_best(direct_results, team_hint)
        if direct_best:
            if not best or direct_best[0] > best[0]:
                best = direct_best

        if best and best[0] >= MIN_SCORE:
            return self._to_resolved(*best)
        return None

    async def _guess_latin_name(self, query: str) -> Optional[str]:
        if not self._llm:
            return None
        prompt = (
            "You are a football player name resolver. "
            "The user gives a player name in ANY language/script/spelling/nickname. "
            "Your job: return the player's REAL NAME in Latin script as used in official databases.\n\n"
            "Examples:\n"
            "- 'Нико Орайли' → 'Nico O'Reilly'\n"
            "- 'Рюдигер' → 'Antonio Rudiger'\n"
            "- 'Мбаппе' → 'Kylian Mbappe'\n"
            "- 'Холанд' → 'Erling Haaland'\n"
            "- 'Анхель ди Мария' → 'Angel Di Maria'\n"
            "- 'Щесны' → 'Wojciech Szczesny'\n\n"
            "Reply with ONLY the full name in Latin script, nothing else.\n"
            f"Query: {query}"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_translate,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            return await asyncio.to_thread(_call)
        except Exception:
            return None

    async def search_coach_info(self, query: str) -> Optional[Dict]:
        """Use search model to get current coach info for a team."""
        if not self._llm:
            return None
        prompt = (
            f"Who is the current head coach/manager of {query} football club? "
            f"When were they appointed? "
            f"Reply in this EXACT format (one field per line):\n"
            f"COACH_NAME: <full name>\n"
            f"TEAM: <team name in English>\n"
            f"LEAGUE: <league name: Premier League / LaLiga / Serie A / Bundesliga / Ligue 1 / RPL>\n"
            f"COACH_SINCE: <YYYY-MM-DD appointment date>\n"
            f"PREVIOUS_COACH: <name of previous coach or NONE>\n"
            f"PREVIOUS_COACH_LEFT: <YYYY-MM-DD when previous coach left or NONE>"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            text = re.sub(r'\[\d+\]', '', text)

            result = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = line.split(":", 1)
                key = key.strip().upper().replace("*", "")
                val = val.strip().strip("*")
                if val.upper() in ("NONE", "UNKNOWN", "N/A"):
                    continue

                if key == "COACH_NAME":
                    result["coach_name"] = val
                elif key == "TEAM":
                    result["team"] = val
                elif key == "LEAGUE":
                    result["league"] = val
                elif key == "COACH_SINCE":
                    date_match = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', val)
                    if date_match:
                        d = date_match.group(1)
                        result["coach_since"] = d if len(d) == 10 else d + "-01"
                elif key == "PREVIOUS_COACH":
                    result["previous_coach"] = val
                elif key == "PREVIOUS_COACH_LEFT":
                    date_match = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', val)
                    if date_match:
                        d = date_match.group(1)
                        result["previous_coach_left"] = d if len(d) == 10 else d + "-01"

            return result if result.get("coach_name") else None
        except Exception:
            return None

    async def search_specific_coach(self, coach_name: str, team_name: str) -> Optional[Dict]:
        """Search for a SPECIFIC coach's tenure at a team (may be former coach)."""
        if not self._llm:
            return None
        prompt = (
            f"When was {coach_name} appointed as head coach of {team_name} football club? "
            f"Are they STILL the head coach of {team_name}, or were they fired/left? "
            f"If they left, when exactly?\n\n"
            f"Reply in this EXACT format (dates as YYYY-MM-DD):\n"
            f"COACH_SINCE: <appointment date>\n"
            f"STILL_IN_CHARGE: YES or NO\n"
            f"COACH_UNTIL: <departure date if they left, or CURRENT if still in charge>"
        )
        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            text = re.sub(r'\[\d+\]', '', text)

            result = {}
            still_in_charge = None
            for line in text.splitlines():
                line = line.strip().replace("*", "")
                if "COACH_SINCE" in line.upper():
                    m = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', line)
                    if m:
                        d = m.group(1)
                        result["coach_since"] = d if len(d) == 10 else d + "-01"
                elif "STILL_IN_CHARGE" in line.upper():
                    still_in_charge = "YES" in line.upper()
                elif "COACH_UNTIL" in line.upper():
                    if "CURRENT" in line.upper():
                        result["coach_until"] = None
                    else:
                        m = re.search(r'(\d{4}-\d{2}(?:-\d{2})?)', line)
                        if m:
                            d = m.group(1)
                            result["coach_until"] = d if len(d) == 10 else d + "-28"
            return result if result.get("coach_since") else None
        except Exception:
            return None

    async def search_player_context(
        self, player_name: str, team: str, league: str, season_year: str | None = None,
    ) -> str | None:
        """Search web for player's tactical role and team playing style."""
        if not self._llm:
            return None

        if season_year and season_year != "2025":
            season_str = f"{season_year}/{int(season_year)+1}"
            prompt = (
                f"Football player {player_name}. Season {season_str}.\n\n"
                f"1) Which club did {player_name} play for in {season_str}? "
                f"If they transferred mid-season, state both clubs and when.\n"
                f"2) What was {player_name}'s tactical role and position at that club in {season_str}? "
                f"(e.g. box-to-box midfielder, inverted winger, deep-lying playmaker, pressing forward, etc.)\n"
                f"3) How did {team or 'that club'} play tactically in {season_str}? "
                f"Formation, style (possession / counter-attack / pressing), manager's approach.\n"
                f"4) Was {player_name} a starter, rotation player, or backup in {season_str}?\n\n"
                f"Reply in 5-10 sentences. Be specific about THIS season, not current."
            )
        else:
            season_str = "2025/2026"
            prompt = (
                f"Football player {player_name}, currently at {team} ({league}). Season {season_str}.\n\n"
                f"1) What is {player_name}'s tactical role and position at {team}? "
                f"(e.g. box-to-box midfielder, inverted winger, deep-lying playmaker, etc.)\n"
                f"2) How does {team} play tactically this season? "
                f"Formation, style (possession / counter-attack / pressing), manager's approach.\n"
                f"3) Is {player_name} a starter, rotation player, or key player?\n\n"
                f"Reply in 5-10 sentences. Be specific about THIS season."
            )

        try:
            def _call():
                resp = self._llm.chat.completions.create(
                    model=self.model_search,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip()
            text = await asyncio.to_thread(_call)
            text = re.sub(r'\[\d+\]', '', text)
            return text
        except Exception:
            return None
