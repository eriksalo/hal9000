#!/usr/bin/env python3
"""
HAL 9000 Person Tracker

Tracks multiple people in the camera view, handling:
- Arrival detection (person appears and stays for 3+ seconds)
- Departure detection (person leaves view)
- Greeting cooldowns
- Conversation state per person
"""

import time
import threading
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrackedPerson:
    """Data about a tracked person"""
    name: str
    first_seen: float  # timestamp when first detected
    last_seen: float   # timestamp when last detected
    face_location: Tuple[int, int, int, int]  # (top, right, bottom, left)
    greeted: bool = False
    in_conversation: bool = False
    last_greeted: float = 0  # timestamp of last greeting
    consecutive_frames: int = 0  # frames seen consecutively


class PersonTracker:
    """Tracks people in the camera view"""

    def __init__(self,
                 presence_threshold: float = 3.0,
                 departure_threshold: float = 5.0,
                 greeting_cooldown: float = 300.0):  # 5 minutes default
        """
        Initialize the person tracker.

        Args:
            presence_threshold: Seconds a person must be visible before greeting
            departure_threshold: Seconds without seeing someone before marking departed
            greeting_cooldown: Seconds between greetings for the same person
        """
        self.presence_threshold = presence_threshold
        self.departure_threshold = departure_threshold
        self.greeting_cooldown = greeting_cooldown

        # Currently tracked people: name -> TrackedPerson
        self.tracked: Dict[str, TrackedPerson] = {}

        # Callbacks
        self.on_arrival: Optional[Callable[[str], None]] = None
        self.on_departure: Optional[Callable[[str], None]] = None

        # Thread safety
        self.lock = threading.Lock()

        # Unknown face tracking
        self._unknown_count = 0

    def update(self, detected_faces: List[Tuple[str, Tuple[int, int, int, int]]]):
        """
        Update tracker with newly detected faces.

        Args:
            detected_faces: List of (name, location) tuples from face recognition
                           name is "Unknown" for unrecognized faces
        """
        now = time.time()
        seen_names = set()

        with self.lock:
            for name, location in detected_faces:
                # Handle unknown faces - use a single "Unknown" name for simplicity
                # This means we only track one unknown at a time, but that's fine
                # for the single-person conversation use case
                if name == "Unknown":
                    name = "Unknown"  # Keep as single identity

                seen_names.add(name)

                if name in self.tracked:
                    # Update existing tracked person
                    person = self.tracked[name]
                    person.last_seen = now
                    person.face_location = location
                    person.consecutive_frames += 1

                    # Check if they've been here long enough to greet
                    if not person.greeted and not person.in_conversation:
                        presence_time = now - person.first_seen
                        if presence_time >= self.presence_threshold:
                            # Check cooldown
                            time_since_greeting = now - person.last_greeted
                            if time_since_greeting >= self.greeting_cooldown:
                                print(f"Tracker: triggering arrival for {name}")
                                self._trigger_arrival(name, person)
                            else:
                                print(f"Tracker: {name} in cooldown ({time_since_greeting:.0f}s < {self.greeting_cooldown}s)")
                        else:
                            if person.consecutive_frames % 10 == 1:
                                print(f"Tracker: {name} present {presence_time:.1f}s (need {self.presence_threshold}s)")
                else:
                    # New person detected
                    print(f"Tracker: new person detected: {name}")
                    self.tracked[name] = TrackedPerson(
                        name=name,
                        first_seen=now,
                        last_seen=now,
                        face_location=location,
                        consecutive_frames=1
                    )

            # Check for departures
            departed = []
            for name, person in self.tracked.items():
                if name not in seen_names:
                    # Person not seen this frame
                    person.consecutive_frames = 0

                    time_since_seen = now - person.last_seen
                    if time_since_seen >= self.departure_threshold:
                        departed.append(name)

            # Handle departures
            for name in departed:
                person = self.tracked[name]
                was_in_conversation = person.in_conversation
                del self.tracked[name]

                if was_in_conversation:
                    self._trigger_departure(name)

    def _get_unknown_id(self, location: Tuple[int, int, int, int]) -> str:
        """Generate a consistent ID for an unknown face based on location"""
        # Simple approach: use a counter that resets
        # More sophisticated: could track by location proximity
        self._unknown_count = (self._unknown_count + 1) % 100
        return str(self._unknown_count)

    def _trigger_arrival(self, name: str, person: TrackedPerson):
        """Trigger arrival callback for a person"""
        person.greeted = True
        person.last_greeted = time.time()

        print(f"Person arrived: {name} (present for {time.time() - person.first_seen:.1f}s)")

        if self.on_arrival:
            try:
                self.on_arrival(name)
            except Exception as e:
                print(f"Arrival callback error: {e}")

    def _trigger_departure(self, name: str):
        """Trigger departure callback for a person"""
        print(f"Person departed: {name}")

        if self.on_departure:
            try:
                self.on_departure(name)
            except Exception as e:
                print(f"Departure callback error: {e}")

    def mark_in_conversation(self, name: str):
        """Mark a person as being in a conversation"""
        with self.lock:
            if name in self.tracked:
                self.tracked[name].in_conversation = True

    def mark_conversation_ended(self, name: str):
        """Mark a person's conversation as ended"""
        with self.lock:
            if name in self.tracked:
                self.tracked[name].in_conversation = False
                self.tracked[name].greeted = True
                self.tracked[name].last_greeted = time.time()

    def is_person_present(self, name: str) -> bool:
        """Check if a person is currently in view"""
        with self.lock:
            return name in self.tracked

    def get_tracked_people(self) -> List[str]:
        """Get list of currently tracked people"""
        with self.lock:
            return list(self.tracked.keys())

    def get_known_people(self) -> List[str]:
        """Get list of tracked people who are not unknown"""
        with self.lock:
            return [name for name in self.tracked.keys()
                    if not name.startswith("Unknown")]

    def get_person_in_conversation(self) -> Optional[str]:
        """Get the name of the person currently in conversation, if any"""
        with self.lock:
            for name, person in self.tracked.items():
                if person.in_conversation:
                    return name
            return None

    def should_greet(self, name: str) -> bool:
        """Check if a person should be greeted"""
        with self.lock:
            if name not in self.tracked:
                return False

            person = self.tracked[name]
            now = time.time()

            # Not if already greeted
            if person.greeted:
                return False

            # Not if in conversation
            if person.in_conversation:
                return False

            # Must be present long enough
            presence_time = now - person.first_seen
            if presence_time < self.presence_threshold:
                return False

            # Must not be in cooldown
            time_since_greeting = now - person.last_greeted
            if time_since_greeting < self.greeting_cooldown:
                return False

            return True

    def reset_greeting(self, name: str):
        """Reset greeting state for a person (for testing)"""
        with self.lock:
            if name in self.tracked:
                self.tracked[name].greeted = False
                self.tracked[name].last_greeted = 0

    def clear(self):
        """Clear all tracked people"""
        with self.lock:
            self.tracked.clear()
            self._unknown_count = 0

    def get_debug_info(self) -> Dict:
        """Get debug information about tracked people"""
        now = time.time()
        with self.lock:
            return {
                "tracked_count": len(self.tracked),
                "people": {
                    name: {
                        "presence_time": round(now - p.first_seen, 1),
                        "last_seen_ago": round(now - p.last_seen, 1),
                        "greeted": p.greeted,
                        "in_conversation": p.in_conversation,
                        "consecutive_frames": p.consecutive_frames
                    }
                    for name, p in self.tracked.items()
                }
            }


# Global instance
_person_tracker = None


def get_person_tracker() -> PersonTracker:
    """Get or create the global person tracker"""
    global _person_tracker
    if _person_tracker is None:
        _person_tracker = PersonTracker()
    return _person_tracker
