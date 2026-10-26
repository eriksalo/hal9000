"""HAL's layered memory: per-person files, HAL's own notes, and semantic recall."""

from hal.memory.notes import PersonNotes
from hal.memory.semantic import SemanticMemory
from hal.memory.store import MemoryStore

__all__ = ["MemoryStore", "PersonNotes", "SemanticMemory"]
