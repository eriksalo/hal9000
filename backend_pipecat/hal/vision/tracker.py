"""Arrival / departure tracking for people in the camera view."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from loguru import logger

from hal.vision.faces import UNKNOWN, FaceLocation


@dataclass
class TrackedPerson:
    name: str
    first_seen: float
    last_seen: float
    location: FaceLocation
    greeted: bool = False
    in_conversation: bool = False
    last_greeted: float = 0.0


@dataclass
class PresenceEvent:
    arrived: list[str] = field(default_factory=list)
    departed: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.arrived or self.departed)


class PersonTracker:
    """Debounces raw face detections into arrival/departure events.

    ``update`` is pure bookkeeping and returns the events that fired, so the
    caller (an asyncio loop) decides what to do with them.
    """

    def __init__(self, *, presence_threshold: float, departure_threshold: float, greeting_cooldown: float):
        self.presence_threshold = presence_threshold
        self.departure_threshold = departure_threshold
        self.greeting_cooldown = greeting_cooldown
        self.tracked: dict[str, TrackedPerson] = {}
        self._cooldowns: dict[str, float] = {}

    def update(self, detections: list[tuple[str, FaceLocation]]) -> PresenceEvent:
        now = time.time()
        event = PresenceEvent()
        seen: set[str] = set()

        for name, location in detections:
            seen.add(name)
            person = self.tracked.get(name)
            if person is None:
                self.tracked[name] = TrackedPerson(name=name, first_seen=now, last_seen=now, location=location)
                logger.debug(f"Tracker: new face {name}")
                continue
            person.last_seen = now
            person.location = location
            if person.greeted or person.in_conversation:
                continue
            if now - person.first_seen < self.presence_threshold:
                continue
            if now - self._cooldowns.get(name, 0.0) < self.greeting_cooldown:
                continue
            person.greeted = True
            person.last_greeted = now
            self._cooldowns[name] = now
            event.arrived.append(name)

        for name in list(self.tracked):
            if name in seen:
                continue
            person = self.tracked[name]
            if now - person.last_seen >= self.departure_threshold:
                del self.tracked[name]
                if person.greeted or person.in_conversation:
                    event.departed.append(name)
        return event

    def mark_in_conversation(self, name: str, value: bool) -> None:
        person = self.tracked.get(name)
        if person:
            person.in_conversation = value
            if not value:
                person.greeted = True
                self._cooldowns[name] = time.time()

    def present(self) -> list[str]:
        return list(self.tracked)

    def present_known(self) -> list[str]:
        return [n for n in self.tracked if n != UNKNOWN]

    def debug_info(self) -> dict:
        now = time.time()
        return {
            name: {
                "presence_secs": round(now - p.first_seen, 1),
                "last_seen_secs_ago": round(now - p.last_seen, 1),
                "greeted": p.greeted,
                "in_conversation": p.in_conversation,
            }
            for name, p in self.tracked.items()
        }
