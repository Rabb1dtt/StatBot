"""Async OpenRouter LLM client using httpx."""

import asyncio
import json
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"


class LLMClient:
    """Client for interacting with LLMs via OpenRouter API."""

    def __init__(
        self,
        api_key: str,
        models_config: dict[str, str],
    ) -> None:
        self.api_key = api_key
        self.models_config = models_config
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    # ------------------------------------------------------------------
    # Core chat method
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: list[dict[str, Any]],
        model_type: str = "light",
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        """Send a chat completion request to OpenRouter.

        Returns the assistant's content text.
        """
        model = self.models_config.get(model_type, self.models_config["heavy"])

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://statbot.app",
            "X-Title": "StatBot",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        client = await self._get_client()

        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = await client.post(
                    OPENROUTER_BASE_URL,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                content: str = data["choices"][0]["message"]["content"]
                logger.debug(
                    "LLM response [%s/%s]: %s chars", model_type, model, len(content)
                )
                return content
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (400, 429, 502, 503) and attempt < max_retries - 1:
                    wait = (attempt + 1) * 2
                    logger.warning(
                        "OpenRouter %s (attempt %d/%d), retrying in %ds: %s",
                        status, attempt + 1, max_retries, wait,
                        exc.response.text[:200],
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(
                    "OpenRouter HTTP error %s: %s",
                    status, exc.response.text,
                )
                raise
            except Exception:
                logger.exception("OpenRouter request failed")
                raise
        raise RuntimeError("LLM request failed after retries")

    # ------------------------------------------------------------------
    # Tool calling (agentic loop step)
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        model_type: str = "heavy",
        temperature: float = 0.6,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        """One step of tool calling: send request, return content + tool_calls.

        Returns:
            dict with keys:
            - content: str | None
            - tool_calls: list[dict] | None
        """
        model = self.models_config.get(model_type, self.models_config["heavy"])

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://statbot.app",
            "X-Title": "StatBot",
        }

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools

        client = await self._get_client()

        try:
            response = await client.post(
                OPENROUTER_BASE_URL,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]

            result: dict[str, Any] = {
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls"),
            }

            logger.debug(
                "LLM tool response [%s/%s]: content=%s, tool_calls=%s",
                model_type, model,
                len(result["content"]) if result["content"] else 0,
                len(result["tool_calls"]) if result["tool_calls"] else 0,
            )
            return result
        except httpx.HTTPStatusError as exc:
            logger.error(
                "OpenRouter HTTP error %s: %s",
                exc.response.status_code, exc.response.text,
            )
            raise
        except Exception:
            logger.exception("OpenRouter tool calling request failed")
            raise
