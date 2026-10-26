"""Semantic recall across every conversation, backed by mem0 OSS.

Runs fully on the Pi: a local on-disk Qdrant collection plus a small
sentence-transformers embedder. Claude (Haiku) does mem0's fact extraction.
Everything is optional: if mem0 is not installed or disabled, calls are no-ops.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from loguru import logger

try:
    from mem0 import Memory as _Mem0Memory

    MEM0_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional extra
    _Mem0Memory = None
    MEM0_AVAILABLE = False


def build_mem0_config(*, qdrant_path: Path, embedder_model: str, anthropic_api_key: str, llm_model: str) -> dict[str, Any]:
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "hal_memories",
                "path": str(qdrant_path),
                "on_disk": True,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {"model": embedder_model},
        },
        "llm": {
            "provider": "anthropic",
            "config": {"model": llm_model, "api_key": anthropic_api_key, "max_tokens": 1500},
        },
        "history_db_path": str(qdrant_path / "history.db"),
        "custom_instructions": (
            "Extract durable facts about the person: work, family, pets, projects, preferences, plans, "
            "opinions. Ignore pleasantries and anything the assistant (HAL) says about itself."
        ),
    }


class SemanticMemory:
    """Thin async wrapper around mem0 with graceful degradation."""

    def __init__(self, config: dict[str, Any] | None, *, enabled: bool = True, recall_limit: int = 5):
        self._memory = None
        self._lock = asyncio.Lock()
        self.recall_limit = recall_limit
        self._config = config
        self._enabled = enabled and MEM0_AVAILABLE and config is not None
        if enabled and not MEM0_AVAILABLE:
            logger.warning("mem0 not installed; semantic memory disabled (pip install mem0ai sentence-transformers)")

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _client(self):
        """Lazily construct the mem0 client off the event loop (model loads are slow)."""
        if self._memory is None and self._enabled:
            async with self._lock:
                if self._memory is None:
                    try:
                        self._memory = await asyncio.to_thread(_Mem0Memory.from_config, self._config)
                        logger.info("Semantic memory ready")
                    except Exception as exc:
                        logger.error(f"Semantic memory unavailable: {exc}")
                        self._enabled = False
        return self._memory

    async def recall(self, query: str, person: str, *, limit: int | None = None) -> list[str]:
        client = await self._client()
        if client is None:
            return []
        try:
            result = await asyncio.to_thread(
                client.search, query, user_id=_user_id(person), top_k=limit or self.recall_limit
            )
        except Exception as exc:
            logger.error(f"Semantic recall failed: {exc}")
            return []
        return [r["memory"] for r in result.get("results", []) if r.get("memory")]

    async def ingest(self, messages: list[dict[str, str]], person: str) -> int:
        """Feed a finished conversation to mem0; returns the number of memories written."""
        client = await self._client()
        if client is None or not messages:
            return 0
        try:
            result = await asyncio.to_thread(client.add, messages, user_id=_user_id(person), infer=True)
        except Exception as exc:
            logger.error(f"Semantic ingest failed: {exc}")
            return 0
        written = len(result.get("results", [])) if isinstance(result, dict) else 0
        logger.info(f"Semantic memory: {written} memories written for {person}")
        return written

    async def all_for(self, person: str, *, limit: int = 50) -> list[str]:
        client = await self._client()
        if client is None:
            return []
        try:
            result = await asyncio.to_thread(client.get_all, user_id=_user_id(person), top_k=limit)
        except Exception as exc:
            logger.error(f"Semantic get_all failed: {exc}")
            return []
        return [r["memory"] for r in result.get("results", []) if r.get("memory")]


def _user_id(person: str) -> str:
    return person.strip().lower().replace(" ", "_") or "unknown"
