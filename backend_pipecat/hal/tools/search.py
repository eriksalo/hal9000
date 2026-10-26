"""Web search for HAL.

Runs Anthropic's server-side web search on a fast side model and returns a
short spoken-style answer, so the conversation model never has to read raw
search results. Falls back to DuckDuckGo snippets if the API call fails.
"""

from __future__ import annotations

import asyncio

import anthropic
from loguru import logger

SEARCH_SYSTEM = (
    "You are a research assistant for a voice agent. Search the web, then answer the question in two or three "
    "plain spoken sentences with the key facts and, if relevant, the date. No markdown, no lists, no URLs."
)


def _web_search_tool(model: str) -> dict:
    # Dynamic-filtering variant needs Opus/Sonnet 4.6+; older models and Haiku take the basic one.
    modern = any(tag in model for tag in ("opus-5", "opus-4-6", "opus-4-7", "opus-4-8", "sonnet-5", "sonnet-4-6", "fable"))
    return {"type": "web_search_20260209" if modern else "web_search_20250305", "name": "web_search", "max_uses": 3}


class WebSearcher:
    def __init__(self, client: anthropic.AsyncAnthropic, *, model: str = "claude-haiku-5-5"):
        self._client = client
        self._model = model

    async def search(self, query: str) -> str:
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=600,
                system=SEARCH_SYSTEM,
                messages=[{"role": "user", "content": query}],
                tools=[_web_search_tool(self._model)],
            )
            if response.stop_reason == "refusal":
                return "I was unable to research that."
            text = " ".join(b.text for b in response.content if b.type == "text").strip()
            if text:
                return text
            logger.warning("Web search returned no text; falling back to DuckDuckGo")
        except anthropic.APIConnectionError as exc:
            logger.warning(f"Web search connection error: {exc}")
        except anthropic.APIStatusError as exc:
            logger.warning(f"Web search API error {exc.status_code}: {exc.message}")
        return await _ddg_fallback(query)


async def _ddg_fallback(query: str, max_results: int = 4) -> str:
    try:
        from ddgs import DDGS
    except ImportError:
        return "Web search is unavailable right now."

    def run() -> list[dict]:
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))

    try:
        results = await asyncio.to_thread(run)
    except Exception as exc:
        logger.error(f"DuckDuckGo search failed: {exc}")
        return "Web search is unavailable right now."
    if not results:
        return f"I found nothing useful about {query}."
    return " ".join(f"{r.get('title', '')}: {r.get('body', '')}" for r in results)
