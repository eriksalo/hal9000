"""End-of-conversation reflection: what should HAL remember?

Uses a cheap side model (Haiku by default) with a strict JSON schema so the
result is always parseable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic
from loguru import logger

from hal.prompts import FACT_EXTRACTION_SCHEMA, FACT_EXTRACTION_SYSTEM, fact_extraction_user_message


@dataclass
class Reflection:
    facts: list[str] = field(default_factory=list)
    summary: str = ""
    mood: str = ""
    open_threads: list[str] = field(default_factory=list)


class ConversationReflector:
    def __init__(self, client: anthropic.AsyncAnthropic, *, model: str = "claude-haiku-5-5"):
        self._client = client
        self._model = model

    async def reflect(self, person_name: str, transcript: str, existing_notes: str) -> Reflection:
        if not transcript.strip():
            return Reflection()
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=FACT_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": fact_extraction_user_message(person_name, transcript, existing_notes)}],
                output_config={"format": {"type": "json_schema", "schema": FACT_EXTRACTION_SCHEMA}},
            )
        except anthropic.APIConnectionError as exc:
            logger.error(f"Reflection skipped (connection): {exc}")
            return Reflection()
        except anthropic.APIStatusError as exc:
            logger.error(f"Reflection skipped (API {exc.status_code}): {exc.message}")
            return Reflection()

        if response.stop_reason == "refusal":
            logger.warning("Reflection refused by safety classifier")
            return Reflection()
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.error(f"Reflection returned invalid JSON: {exc}")
            return Reflection()
        return Reflection(
            facts=[f for f in data.get("facts", []) if isinstance(f, str)],
            summary=data.get("summary", ""),
            mood=data.get("mood", ""),
            open_threads=[t for t in data.get("open_threads", []) if isinstance(t, str)],
        )
