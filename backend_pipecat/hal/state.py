"""Shared runtime state: what HAL is doing right now.

Written by the pipeline and presence monitor, read by the status server that
feeds the ESP32 eye display and the debug UI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Literal

HALMode = Literal["idle", "listening", "thinking", "speaking", "offline"]


@dataclass
class HALState:
    mode: HALMode = "idle"
    person: str | None = None
    people_present: list[str] = field(default_factory=list)
    in_conversation: bool = False
    online: bool = True
    last_user_text: str = ""
    last_hal_text: str = ""
    updated_at: float = field(default_factory=time.time)
    conversation_count: int = 0

    def set_mode(self, mode: HALMode) -> None:
        self.mode = mode
        self.updated_at = time.time()

    def display_payload(self) -> dict:
        """Payload for GET /api/hal/display (consumed by the ESP32 firmware)."""
        return {
            "mode": "face" if self.people_present else "eye",
            # The ESP32 string-matches "listening"/"speaking" in this field.
            "state": self.mode,
            "person": self.person or (self.people_present[0] if self.people_present else None),
        }

    def status_payload(self) -> dict:
        return {
            "mode": self.mode,
            "person": self.person,
            "people_present": self.people_present,
            "in_conversation": self.in_conversation,
            "online": self.online,
            "last_user_text": self.last_user_text,
            "last_hal_text": self.last_hal_text,
            "conversation_count": self.conversation_count,
            "updated_at": self.updated_at,
        }
