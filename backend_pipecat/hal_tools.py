#!/usr/bin/env python3
"""
HAL 9000 Claude Tools

Function calling tools for Claude to access web search, memory, and other capabilities.
"""

import json
from typing import Any, Dict, List, Optional
from datetime import datetime
from loguru import logger

try:
    from duckduckgo_search import DDGS
    DDGS_AVAILABLE = True
except ImportError:
    DDGS_AVAILABLE = False
    logger.warning("duckduckgo_search not available - web search disabled")


class HALTools:
    """
    Tool provider for HAL's Claude LLM integration.
    Provides web search, memory access, and other capabilities.
    """

    def __init__(self, memory_store=None, person_name: Optional[str] = None):
        """
        Initialize HAL tools.

        Args:
            memory_store: MemoryStore instance for accessing conversation history
            person_name: Name of person HAL is talking to
        """
        self.memory_store = memory_store
        self.person_name = person_name

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """
        Get Anthropic-compatible tool definitions for Claude.

        Returns:
            List of tool definition dictionaries
        """
        tools = []

        # Web search tool
        if DDGS_AVAILABLE:
            tools.append({
                "name": "web_search",
                "description": (
                    "Search the web for current information using DuckDuckGo. "
                    "Use this when you need up-to-date information, facts, news, "
                    "or information beyond your knowledge cutoff. "
                    "Returns a list of search results with titles, snippets, and URLs."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (1-10)",
                            "default": 5
                        }
                    },
                    "required": ["query"]
                }
            })

        # Memory recall tool
        if self.memory_store and self.person_name:
            tools.append({
                "name": "recall_memory",
                "description": (
                    f"Recall previous conversations and facts about {self.person_name}. "
                    "Use this to remember what you've learned about the person in past interactions. "
                    "Returns profile information, conversation history, and known facts."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Optional search query to filter memories"
                        }
                    },
                    "required": []
                }
            })

        # Get current time tool
        tools.append({
            "name": "get_current_time",
            "description": (
                "Get the current date and time. "
                "Use this when you need to know what time it is or the current date."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        })

        return tools

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        Execute a tool call from Claude.

        Args:
            tool_name: Name of the tool to execute
            tool_input: Input parameters for the tool

        Returns:
            Tool execution result as string
        """
        logger.info(f"Executing tool: {tool_name} with input: {tool_input}")

        try:
            if tool_name == "web_search":
                return await self._web_search(
                    tool_input.get("query"),
                    tool_input.get("max_results", 5)
                )

            elif tool_name == "recall_memory":
                return await self._recall_memory(
                    tool_input.get("query")
                )

            elif tool_name == "get_current_time":
                return await self._get_current_time()

            else:
                return f"Error: Unknown tool '{tool_name}'"

        except Exception as e:
            logger.error(f"Tool execution error: {e}")
            return f"Error executing tool: {e}"

    async def _web_search(self, query: str, max_results: int = 5) -> str:
        """
        Perform web search using DuckDuckGo.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            Formatted search results
        """
        if not DDGS_AVAILABLE:
            return "Web search is not available (duckduckgo_search not installed)"

        try:
            logger.info(f"Web search: {query}")

            # Perform search
            results = []
            with DDGS() as ddgs:
                search_results = ddgs.text(query, max_results=max_results)

                for i, result in enumerate(search_results, 1):
                    results.append(
                        f"{i}. {result.get('title', 'No title')}\n"
                        f"   {result.get('body', 'No description')}\n"
                        f"   URL: {result.get('href', 'No URL')}"
                    )

            if not results:
                return f"No results found for query: {query}"

            return "Web search results:\n\n" + "\n\n".join(results)

        except Exception as e:
            logger.error(f"Web search error: {e}")
            return f"Web search failed: {e}"

    async def _recall_memory(self, query: Optional[str] = None) -> str:
        """
        Recall information from memory store.

        Args:
            query: Optional search query to filter memories

        Returns:
            Formatted memory information
        """
        if not self.memory_store or not self.person_name:
            return "Memory system not available"

        try:
            logger.info(f"Recalling memory for {self.person_name}, query: {query}")

            # Get profile
            profile = self.memory_store.load_profile(self.person_name)

            # Format memory information
            memory_text = f"Memory for {self.person_name}:\n\n"

            # Add profile information
            if profile:
                memory_text += "Profile:\n"
                memory_text += f"  Name: {profile.get('name', 'Unknown')}\n"
                memory_text += f"  Conversations: {profile.get('conversation_count', 0)}\n"
                memory_text += f"  Last seen: {profile.get('last_seen', 'Never')}\n"

                # Add known facts
                facts = profile.get('facts', [])
                if facts:
                    memory_text += f"\nKnown facts ({len(facts)}):\n"
                    for fact in facts[:10]:  # Limit to 10 most recent facts
                        memory_text += f"  - {fact}\n"

            # TODO: Add semantic search through conversations if query is provided
            # TODO: Add context from recent conversations

            return memory_text

        except Exception as e:
            logger.error(f"Memory recall error: {e}")
            return f"Memory recall failed: {e}"

    async def _get_current_time(self) -> str:
        """
        Get current date and time.

        Returns:
            Formatted current time
        """
        now = datetime.now()
        formatted_time = now.strftime("%A, %B %d, %Y at %I:%M %p")
        return f"Current time: {formatted_time}"


def create_tool_handler(memory_store=None, person_name: Optional[str] = None):
    """
    Create a tool handler for use with Pipecat's Claude LLM service.

    Args:
        memory_store: MemoryStore instance
        person_name: Name of person HAL is talking to

    Returns:
        HALTools instance configured for Claude tool calling
    """
    return HALTools(memory_store=memory_store, person_name=person_name)
