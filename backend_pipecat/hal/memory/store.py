"""Per-person filesystem memory.

Layout::

    memory/people/{slug}/
        profile.json              facts, counters, timestamps
        notes.md                  HAL's own free-form notes (see notes.py)
        summary.json              rolling conversation summaries
        conversations/{ts}.json   full transcripts
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("_", name.strip().lower()).strip("_") or "unknown"


@dataclass
class Utterance:
    speaker: str
    text: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def as_dict(self) -> dict[str, str]:
        return {"speaker": self.speaker, "text": self.text, "timestamp": self.timestamp}


@dataclass
class ConversationRecord:
    person_name: str
    started_at: datetime
    utterances: list[Utterance] = field(default_factory=list)
    ended_at: datetime | None = None
    end_reason: str | None = None
    summary: str | None = None
    extracted_facts: list[str] = field(default_factory=list)
    mood: str | None = None
    open_threads: list[str] = field(default_factory=list)

    def add(self, speaker: str, text: str) -> None:
        text = text.strip()
        if text:
            self.utterances.append(Utterance(speaker=speaker, text=text))

    def transcript(self) -> str:
        return "\n".join(f"{u.speaker}: {u.text}" for u in self.utterances)

    def as_messages(self) -> list[dict[str, str]]:
        """Transcript as role/content messages (for mem0 ingestion)."""
        return [
            {"role": "assistant" if u.speaker.upper() == "HAL" else "user", "content": u.text}
            for u in self.utterances
        ]

    def as_dict(self) -> dict[str, Any]:
        return {
            "person_name": self.person_name,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "ended_at": self.ended_at.isoformat(timespec="seconds") if self.ended_at else None,
            "end_reason": self.end_reason,
            "summary": self.summary,
            "mood": self.mood,
            "extracted_facts": self.extracted_facts,
            "open_threads": self.open_threads,
            "utterances": [u.as_dict() for u in self.utterances],
        }


class MemoryStore:
    def __init__(self, base_dir: Path):
        self.people_dir = base_dir / "people"
        self.people_dir.mkdir(parents=True, exist_ok=True)

    # ---- paths -----------------------------------------------------------

    def person_dir(self, name: str) -> Path:
        path = self.people_dir / slugify(name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _profile_path(self, name: str) -> Path:
        return self.person_dir(name) / "profile.json"

    def _summary_path(self, name: str) -> Path:
        return self.person_dir(name) / "summary.json"

    def _conversations_dir(self, name: str) -> Path:
        path = self.person_dir(name) / "conversations"
        path.mkdir(exist_ok=True)
        return path

    # ---- profile -----------------------------------------------------------

    def load_profile(self, name: str) -> dict[str, Any]:
        path = self._profile_path(name)
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.error(f"Corrupt profile for {name}: {exc}")
        return {
            "name": name,
            "first_seen": datetime.now().isoformat(timespec="seconds"),
            "last_seen": None,
            "facts": [],
            "conversation_count": 0,
        }

    def save_profile(self, name: str, profile: dict[str, Any]) -> None:
        self._profile_path(name).write_text(json.dumps(profile, indent=2), encoding="utf-8")

    def add_facts(self, name: str, facts: list[str]) -> int:
        profile = self.load_profile(name)
        existing = profile.setdefault("facts", [])
        added = 0
        for fact in facts:
            fact = fact.strip()
            if fact and fact not in existing:
                existing.append(fact)
                added += 1
        if added:
            self.save_profile(name, profile)
        return added

    def person_exists(self, name: str) -> bool:
        return (self.people_dir / slugify(name) / "profile.json").exists()

    def list_known_people(self) -> list[str]:
        names: list[str] = []
        for path in sorted(self.people_dir.glob("*/profile.json")):
            try:
                names.append(json.loads(path.read_text(encoding="utf-8")).get("name", path.parent.name))
            except (OSError, json.JSONDecodeError):
                names.append(path.parent.name)
        return names

    # ---- conversations ------------------------------------------------------

    def start_conversation(self, name: str) -> ConversationRecord:
        profile = self.load_profile(name)
        profile["conversation_count"] = profile.get("conversation_count", 0) + 1
        profile["last_seen"] = datetime.now().isoformat(timespec="seconds")
        self.save_profile(name, profile)
        return ConversationRecord(person_name=name, started_at=datetime.now())

    def finish_conversation(self, record: ConversationRecord, reason: str) -> Path | None:
        record.ended_at = datetime.now()
        record.end_reason = reason
        if not record.utterances:
            logger.info(f"Conversation with {record.person_name} had no utterances; not saved")
            return None
        path = self._conversations_dir(record.person_name) / (record.started_at.strftime("%Y-%m-%d_%H%M%S") + ".json")
        path.write_text(json.dumps(record.as_dict(), indent=2), encoding="utf-8")
        if record.extracted_facts:
            self.add_facts(record.person_name, record.extracted_facts)
        if record.summary:
            self._append_summary(record.person_name, record.summary, record.open_threads)
        logger.info(f"Saved conversation with {record.person_name} to {path.name}")
        return path

    def _append_summary(self, name: str, summary: str, open_threads: list[str]) -> None:
        path = self._summary_path(name)
        summaries: list[dict[str, Any]] = []
        if path.exists():
            try:
                summaries = json.loads(path.read_text(encoding="utf-8")).get("summaries", [])
            except (OSError, json.JSONDecodeError):
                summaries = []
        summaries.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "summary": summary,
                "open_threads": open_threads,
            }
        )
        path.write_text(json.dumps({"summaries": summaries[-20:]}, indent=2), encoding="utf-8")

    def recent_conversations(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        files = sorted(self._conversations_dir(name).glob("*.json"), reverse=True)[:limit]
        records: list[dict[str, Any]] = []
        for path in files:
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(f"Skipping unreadable conversation {path.name}: {exc}")
        return records

    # ---- context for the LLM ---------------------------------------------------

    def profile_summary(self, name: str, *, max_facts: int = 15, max_summaries: int = 3) -> str:
        """Compact, human-readable relationship summary for the system prompt."""
        profile = self.load_profile(name)
        lines: list[str] = []
        first_seen = profile.get("first_seen")
        if first_seen:
            lines.append(f"First met: {_pretty_date(first_seen)}")
        last_seen = profile.get("last_seen")
        if last_seen:
            lines.append(f"Last conversation: {_pretty_date(last_seen)}")
        count = profile.get("conversation_count", 0)
        if count:
            lines.append(f"Conversations so far: {count}")
        facts = profile.get("facts", [])[-max_facts:]
        if facts:
            lines.append("Known facts:")
            lines += [f"- {f}" for f in facts]
        path = self._summary_path(name)
        if path.exists():
            try:
                summaries = json.loads(path.read_text(encoding="utf-8")).get("summaries", [])[-max_summaries:]
            except (OSError, json.JSONDecodeError):
                summaries = []
            if summaries:
                lines.append("Recent conversations:")
                for s in summaries:
                    lines.append(f"- [{_pretty_date(s.get('timestamp', ''))}] {s.get('summary', '')}")
                    for thread in s.get("open_threads", []):
                        lines.append(f"  (follow up: {thread})")
        return "\n".join(lines)


def _pretty_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%B %d, %Y")
    except ValueError:
        return iso
