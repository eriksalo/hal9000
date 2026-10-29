"""Typed configuration loaded from environment variables / .env.

Every knob HAL needs lives here so the rest of the package never touches
``os.environ`` directly. Call :func:`load_config` once at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from loguru import logger

STTProvider = Literal["deepgram_flux", "deepgram", "hailo", "whisper", "moonshine"]
TTSProvider = Literal["cartesia", "elevenlabs", "piper"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    return float(raw) if raw else default


def _env_path(name: str, default: Path) -> Path:
    raw = _env(name)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str = "claude-opus-5-5"
    effort: Effort = "low"
    side_model: str = "claude-haiku-5-5"
    max_tokens: int = 1024
    enable_prompt_caching: bool = True
    system_prompt_cache_ttl: Literal["5m", "1h"] = "1h"
    enable_web_search: bool = True
    enable_vision: bool = True


@dataclass(frozen=True)
class STTConfig:
    provider: STTProvider = "deepgram_flux"
    fallback_provider: STTProvider = "whisper"
    deepgram_api_key: str = ""
    keyterms: tuple[str, ...] = ("HAL", "Dave", "Discovery")
    whisper_model: str = "base.en"
    hailo_variant: str = "small"
    language: str = "en"


@dataclass(frozen=True)
class TTSConfig:
    provider: TTSProvider = "cartesia"
    fallback_provider: TTSProvider = "piper"
    cartesia_api_key: str = ""
    cartesia_voice_id: str = ""
    cartesia_model: str = "sonic-3"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model: str = "eleven_flash_v2_5"
    piper_url: str = "http://localhost:5002"
    piper_model_path: Path = PROJECT_ROOT / "hal_9000_model" / "hal.onnx"
    piper_sample_rate: int = 22050


@dataclass(frozen=True)
class AudioConfig:
    input_device_index: int | None = None
    output_device_index: int | None = None
    sample_rate: int = 16000
    output_sample_rate: int = 24000
    input_gain: float = 1.0
    input_gate_rms: float = 0.0
    input_target_rms: float = 0.0
    input_max_gain: float = 30.0


@dataclass(frozen=True)
class TurnConfig:
    """Local turn-taking knobs (used when STT does not provide its own EOT)."""

    smart_turn_enabled: bool = True
    smart_turn_cpu_count: int = 2
    smart_turn_stop_secs: float = 2.0
    vad_stop_secs: float = 0.2
    vad_confidence: float = 0.6
    vad_min_volume: float = 0.0
    idle_timeout_secs: float = 90.0


@dataclass(frozen=True)
class WakeConfig:
    """Local wake-word detection (openWakeWord) so idle costs nothing."""

    enabled: bool = True
    model_path: str = "hey_jarvis"  # stock model name, or a path to a custom .onnx
    threshold: float = 0.5
    trigger_frames: int = 1
    refractory_secs: float = 3.0
    inference_framework: str = "onnx"
    vad_threshold: float = 0.0


@dataclass(frozen=True)
class MemoryConfig:
    base_dir: Path = PROJECT_ROOT / "memory"
    semantic_enabled: bool = True
    qdrant_path: Path = PROJECT_ROOT / "memory" / "qdrant"
    embedder_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    recall_limit: int = 5


@dataclass(frozen=True)
class VisionConfig:
    enabled: bool = True
    camera_type: Literal["picamera2", "opencv"] = "picamera2"
    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 15
    rotate_180: bool = False
    face_database: Path = PROJECT_ROOT / "face_database.json"
    face_tolerance: float = 0.6
    presence_threshold_secs: float = 3.0
    departure_threshold_secs: float = 5.0
    greeting_cooldown_secs: float = 300.0
    detection_interval_secs: float = 0.2
    name_hold_secs: float = 60.0


@dataclass(frozen=True)
class HailoConfig:
    enabled: bool = False
    ollama_url: str = "http://localhost:8000"
    offline_model: str = "qwen3:1.7b"
    vlm_enabled: bool = False


@dataclass(frozen=True)
class ServerConfig:
    status_port: int = 5000
    webrtc_port: int = 7860
    host: str = "0.0.0.0"


@dataclass(frozen=True)
class HALConfig:
    llm: LLMConfig
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    turn: TurnConfig = field(default_factory=TurnConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    hailo: HailoConfig = field(default_factory=HailoConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    wake: WakeConfig = field(default_factory=WakeConfig)
    default_person: str = "Dave"
    timezone: str = "America/Denver"
    log_level: str = "INFO"

    def validate(self) -> list[str]:
        """Return human-readable problems; empty list means the config is usable."""
        problems: list[str] = []
        if not self.llm.api_key:
            problems.append("ANTHROPIC_API_KEY is not set")
        if self.stt.provider in {"deepgram_flux", "deepgram"} and not self.stt.deepgram_api_key:
            problems.append(f"STT_PROVIDER={self.stt.provider} requires DEEPGRAM_API_KEY")
        if self.tts.provider == "cartesia" and not (self.tts.cartesia_api_key and self.tts.cartesia_voice_id):
            problems.append("TTS_PROVIDER=cartesia requires CARTESIA_API_KEY and CARTESIA_VOICE_ID")
        if self.tts.provider == "elevenlabs" and not (self.tts.elevenlabs_api_key and self.tts.elevenlabs_voice_id):
            problems.append("TTS_PROVIDER=elevenlabs requires ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID")
        return problems


def _optional_int(name: str) -> int | None:
    raw = _env(name)
    return int(raw) if raw else None


def load_config(dotenv_path: Path | None = None) -> HALConfig:
    """Build a :class:`HALConfig` from the environment (loading ``.env`` first)."""
    load_dotenv(dotenv_path)

    config = HALConfig(
        llm=LLMConfig(
            api_key=_env("ANTHROPIC_API_KEY"),
            model=_env("LLM_MODEL", "claude-opus-5-5"),
            effort=_env("LLM_EFFORT", "low"),  # type: ignore[arg-type]
            side_model=_env("LLM_SIDE_MODEL", "claude-haiku-5-5"),
            max_tokens=_env_int("LLM_MAX_TOKENS", 1024),
            enable_prompt_caching=_env_bool("LLM_PROMPT_CACHING", True),
            system_prompt_cache_ttl=_env("LLM_CACHE_TTL", "1h"),  # type: ignore[arg-type]
            enable_web_search=_env_bool("LLM_WEB_SEARCH", True),
            enable_vision=_env_bool("LLM_VISION", True),
        ),
        stt=STTConfig(
            provider=_env("STT_PROVIDER", "deepgram_flux"),  # type: ignore[arg-type]
            fallback_provider=_env("STT_FALLBACK_PROVIDER", "whisper"),  # type: ignore[arg-type]
            deepgram_api_key=_env("DEEPGRAM_API_KEY"),
            keyterms=tuple(k.strip() for k in _env("STT_KEYTERMS", "HAL,Dave,Discovery").split(",") if k.strip()),
            whisper_model=_env("WHISPER_MODEL", "base.en"),
            hailo_variant=_env("HAILO_WHISPER_VARIANT", "small"),
            language=_env("STT_LANGUAGE", "en"),
        ),
        tts=TTSConfig(
            provider=_env("TTS_PROVIDER", "cartesia"),  # type: ignore[arg-type]
            fallback_provider=_env("TTS_FALLBACK_PROVIDER", "piper"),  # type: ignore[arg-type]
            cartesia_api_key=_env("CARTESIA_API_KEY"),
            cartesia_voice_id=_env("CARTESIA_VOICE_ID"),
            cartesia_model=_env("CARTESIA_MODEL", "sonic-3"),
            elevenlabs_api_key=_env("ELEVENLABS_API_KEY"),
            elevenlabs_voice_id=_env("ELEVENLABS_VOICE_ID"),
            elevenlabs_model=_env("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
            piper_url=_env("PIPER_URL", "http://localhost:5002"),
            piper_model_path=_env_path("PIPER_MODEL_PATH", PROJECT_ROOT / "hal_9000_model" / "hal.onnx"),
            piper_sample_rate=_env_int("PIPER_SAMPLE_RATE", 22050),
        ),
        audio=AudioConfig(
            input_device_index=_optional_int("AUDIO_INPUT_DEVICE_INDEX"),
            output_device_index=_optional_int("AUDIO_OUTPUT_DEVICE_INDEX"),
            sample_rate=_env_int("AUDIO_IN_SAMPLE_RATE", 16000),
            output_sample_rate=_env_int("AUDIO_OUT_SAMPLE_RATE", 24000),
            input_gain=_env_float("AUDIO_INPUT_GAIN", 1.0),
            input_gate_rms=_env_float("AUDIO_INPUT_GATE_RMS", 0.0),
            input_target_rms=_env_float("AUDIO_INPUT_TARGET_RMS", 0.0),
            input_max_gain=_env_float("AUDIO_INPUT_MAX_GAIN", 30.0),
        ),
        turn=TurnConfig(
            smart_turn_enabled=_env_bool("SMART_TURN_ENABLED", True),
            smart_turn_cpu_count=_env_int("SMART_TURN_CPU_COUNT", 2),
            smart_turn_stop_secs=_env_float("SMART_TURN_STOP_SECS", 2.0),
            vad_stop_secs=_env_float("VAD_STOP_SECS", 0.2),
            vad_confidence=_env_float("VAD_CONFIDENCE", 0.6),
            vad_min_volume=_env_float("VAD_MIN_VOLUME", 0.0),
            idle_timeout_secs=_env_float("IDLE_TIMEOUT_SECS", 90.0),
        ),
        memory=MemoryConfig(
            base_dir=_env_path("MEMORY_DIR", PROJECT_ROOT / "memory"),
            semantic_enabled=_env_bool("MEMORY_SEMANTIC_ENABLED", True),
            qdrant_path=_env_path("QDRANT_PATH", PROJECT_ROOT / "memory" / "qdrant"),
            embedder_model=_env("MEMORY_EMBEDDER_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            recall_limit=_env_int("MEMORY_RECALL_LIMIT", 5),
        ),
        vision=VisionConfig(
            enabled=_env_bool("VISION_ENABLED", True),
            camera_type=_env("CAMERA_TYPE", "picamera2"),  # type: ignore[arg-type]
            camera_index=_env_int("CAMERA_INDEX", 0),
            width=_env_int("CAMERA_WIDTH", 1280),
            height=_env_int("CAMERA_HEIGHT", 720),
            fps=_env_int("CAMERA_FPS", 15),
            rotate_180=_env_bool("CAMERA_ROTATE_180", False),
            face_database=_env_path("FACE_DATABASE", PROJECT_ROOT / "face_database.json"),
            face_tolerance=_env_float("FACE_TOLERANCE", 0.6),
            presence_threshold_secs=_env_float("PRESENCE_THRESHOLD_SECS", 3.0),
            departure_threshold_secs=_env_float("DEPARTURE_THRESHOLD_SECS", 5.0),
            greeting_cooldown_secs=_env_float("GREETING_COOLDOWN_SECS", 300.0),
            detection_interval_secs=_env_float("DETECTION_INTERVAL_SECS", 0.2),
            name_hold_secs=_env_float("NAME_HOLD_SECS", 60.0),
        ),
        hailo=HailoConfig(
            enabled=_env_bool("HAILO_ENABLED", False),
            ollama_url=_env("HAILO_OLLAMA_URL", "http://localhost:8000"),
            offline_model=_env("HAILO_OFFLINE_MODEL", "qwen3:1.7b"),
            vlm_enabled=_env_bool("HAILO_VLM_ENABLED", False),
        ),
        server=ServerConfig(
            status_port=_env_int("STATUS_PORT", 5000),
            webrtc_port=_env_int("WEBRTC_PORT", 7860),
            host=_env("SERVER_HOST", "0.0.0.0"),
        ),
        wake=WakeConfig(
            enabled=_env_bool("WAKE_ENABLED", True),
            model_path=_env("WAKE_MODEL", "hey_jarvis"),
            threshold=_env_float("WAKE_THRESHOLD", 0.5),
            trigger_frames=_env_int("WAKE_TRIGGER_FRAMES", 1),
            refractory_secs=_env_float("WAKE_REFRACTORY_SECS", 3.0),
            inference_framework=_env("WAKE_FRAMEWORK", "onnx"),
            vad_threshold=_env_float("WAKE_VAD_THRESHOLD", 0.0),
        ),
        default_person=_env("PERSON_NAME", "Dave"),
        timezone=_env("TIMEZONE", "America/Denver"),
        log_level=_env("LOG_LEVEL", "INFO"),
    )

    for problem in config.validate():
        logger.warning(f"Config: {problem}")
    return config
