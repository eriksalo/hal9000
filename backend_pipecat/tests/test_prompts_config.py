import json

from hal.config import load_config
from hal.prompts import (
    FACT_EXTRACTION_SCHEMA,
    HAL_PERSONA,
    conversation_system_prompt,
    greeting_instruction,
    presence_update,
)
from hal.state import HALState


def test_system_prompt_persona_is_stable_prefix():
    prompt_a = conversation_system_prompt("Erik", notes="likes tea", profile_summary="", semantic_memories=["x"])
    prompt_b = conversation_system_prompt("Dave", notes="", profile_summary="", semantic_memories=[])
    assert prompt_a.startswith(HAL_PERSONA)
    assert prompt_b.startswith(HAL_PERSONA)
    assert "likes tea" in prompt_a
    assert "no notes on Dave" in prompt_b
    assert "markdown" in HAL_PERSONA.lower()


def test_greeting_and_presence_text():
    assert "never met" in greeting_instruction("Dave", is_first_meeting=True)
    assert "Dave" in greeting_instruction("Dave", is_first_meeting=False)
    note = presence_update(["Chris"], ["Erik"])
    assert "Chris" in note and "Erik" in note


def test_extraction_schema_is_strict_json_schema():
    assert FACT_EXTRACTION_SCHEMA["additionalProperties"] is False
    assert set(FACT_EXTRACTION_SCHEMA["required"]) == {"facts", "summary", "mood", "open_threads"}
    json.dumps(FACT_EXTRACTION_SCHEMA)


def test_config_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("STT_PROVIDER", "whisper")
    monkeypatch.setenv("TTS_PROVIDER", "piper")
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("AUDIO_INPUT_DEVICE_INDEX", "3")
    monkeypatch.setenv("STT_KEYTERMS", "HAL, Dave ,,Pod bay")
    config = load_config(dotenv_path=tmp_path / "nonexistent.env")
    assert config.validate() == []
    assert config.llm.model == "claude-opus-5-5"
    assert config.stt.keyterms == ("HAL", "Dave", "Pod bay")
    assert config.audio.input_device_index == 3
    assert config.memory.base_dir == tmp_path / "mem"


def test_config_validation_reports_missing_keys(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("STT_PROVIDER", "deepgram_flux")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "")
    monkeypatch.setenv("TTS_PROVIDER", "cartesia")
    monkeypatch.setenv("CARTESIA_API_KEY", "")
    config = load_config(dotenv_path=tmp_path / "nonexistent.env")
    problems = config.validate()
    assert any("ANTHROPIC_API_KEY" in p for p in problems)
    assert any("DEEPGRAM_API_KEY" in p for p in problems)
    assert any("CARTESIA" in p for p in problems)


def test_display_payload_matches_esp32_contract():
    state = HALState()
    assert state.display_payload() == {"mode": "eye", "state": "idle", "person": None}
    state.people_present = ["Erik"]
    state.set_mode("speaking")
    payload = state.display_payload()
    assert payload["mode"] == "face" and payload["person"] == "Erik" and "speaking" in payload["state"]
