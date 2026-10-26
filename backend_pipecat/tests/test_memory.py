from pathlib import Path

from hal.memory.notes import PersonNotes
from hal.memory.store import ConversationRecord, MemoryStore, slugify


def test_slugify():
    assert slugify("Erik Salo") == "erik_salo"
    assert slugify("  ") == "unknown"
    assert slugify("D'Artagnan!") == "d_artagnan"


def test_profile_roundtrip_and_facts(tmp_path: Path):
    store = MemoryStore(tmp_path)
    profile = store.load_profile("Erik")
    assert profile["conversation_count"] == 0
    assert store.add_facts("Erik", ["Owns a Voron 2.4", "Owns a Voron 2.4", ""]) == 1
    assert store.load_profile("Erik")["facts"] == ["Owns a Voron 2.4"]
    assert store.list_known_people() == ["Erik"]
    assert store.person_exists("erik salo") is False


def test_conversation_lifecycle(tmp_path: Path):
    store = MemoryStore(tmp_path)
    record = store.start_conversation("Erik")
    assert store.load_profile("Erik")["conversation_count"] == 1
    record.add("Erik", "I just finished building my printer.")
    record.add("HAL", "I trust it is functioning normally.")
    record.add("HAL", "   ")
    record.summary = "Erik finished a printer build."
    record.extracted_facts = ["Recently finished building a 3D printer"]
    record.open_threads = ["Ask how the first print went"]
    path = store.finish_conversation(record, "goodbye")
    assert path is not None and path.exists()
    assert len(record.utterances) == 2
    assert record.as_messages()[1]["role"] == "assistant"

    summary = store.profile_summary("Erik")
    assert "Recently finished building a 3D printer" in summary
    assert "Ask how the first print went" in summary
    assert store.recent_conversations("Erik")[0]["end_reason"] == "goodbye"


def test_empty_conversation_not_saved(tmp_path: Path):
    store = MemoryStore(tmp_path)
    record = ConversationRecord(person_name="Erik", started_at=__import__("datetime").datetime.now())
    assert store.finish_conversation(record, "silence") is None


def test_notes_append_replace_dedupe(tmp_path: Path):
    notes = PersonNotes(tmp_path)
    assert notes.read() == ""
    notes.append("Has a dog named Max")
    notes.append("Has a dog named Max")
    assert notes.read().count("Max") == 1
    assert notes.replace("Max", "Rex") is True
    assert "Rex" in notes.read()
    assert notes.replace("nothing here", "x") is False
    notes.write("fresh")
    assert notes.read() == "fresh\n"
