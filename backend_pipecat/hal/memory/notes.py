"""HAL's own notes about a person: a markdown file HAL reads and edits itself.

This mirrors the shape of Anthropic's memory tool (view / append / replace) but
is scoped to one person and exposed to Claude as ordinary function tools, so it
works through Pipecat's tool-calling path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger

MAX_NOTES_CHARS = 12_000


class PersonNotes:
    def __init__(self, person_dir: Path):
        self.path = person_dir / "notes.md"

    def read(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error(f"Cannot read notes {self.path}: {exc}")
            return ""

    def write(self, content: str) -> None:
        content = content.strip() + "\n"
        if len(content) > MAX_NOTES_CHARS:
            logger.warning(f"Notes for {self.path.parent.name} exceed {MAX_NOTES_CHARS} chars; truncating oldest")
            content = content[-MAX_NOTES_CHARS:]
        self.path.write_text(content, encoding="utf-8")

    def append(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        stamp = datetime.now().strftime("%Y-%m-%d")
        current = self.read()
        line = f"- ({stamp}) {text}"
        if line in current or text in current:
            return
        self.write((current.rstrip() + "\n" + line) if current.strip() else line)

    def replace(self, old: str, new: str) -> bool:
        current = self.read()
        if old not in current:
            return False
        self.write(current.replace(old, new, 1))
        return True
