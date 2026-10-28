"""Speech-to-text factory.

Primary: Deepgram Flux (cloud, model-integrated end-of-turn, keyterm boosting).
Local fallbacks: Hailo Whisper, faster-whisper on CPU, Moonshine on CPU — all
paired with Silero VAD + Smart Turn v3 running locally for turn detection.
"""

from __future__ import annotations

from loguru import logger
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.services.stt_service import STTService
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from hal.config import HALConfig, STTProvider


def build_stt(config: HALConfig, *, provider: STTProvider | None = None) -> STTService:
    provider = provider or config.stt.provider
    stt_cfg = config.stt
    logger.info(f"STT provider: {provider}")

    if provider == "deepgram_flux":
        from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService

        return DeepgramFluxSTTService(
            api_key=stt_cfg.deepgram_api_key,
            settings=DeepgramFluxSTTService.Settings(
                model="flux-general-en",
                keyterm=list(stt_cfg.keyterms),
                eot_threshold=0.7,
                eot_timeout_ms=4000,
            ),
        )

    if provider == "deepgram":
        from pipecat.services.deepgram.stt import DeepgramSTTService

        return DeepgramSTTService(
            api_key=stt_cfg.deepgram_api_key,
            settings=DeepgramSTTService.Settings(model="nova-3-general", keyterm=list(stt_cfg.keyterms)),
        )

    if provider == "hailo":
        from hal.services.hailo_stt import HailoWhisperSTTService

        return HailoWhisperSTTService(variant=stt_cfg.hailo_variant, sample_rate=config.audio.sample_rate)

    if provider == "whisper":
        from pipecat.services.whisper.stt import WhisperSTTService

        return WhisperSTTService(
            device="cpu",
            compute_type="int8",
            settings=WhisperSTTService.Settings(
                model=stt_cfg.whisper_model,
                hotwords=" ".join(stt_cfg.keyterms),
            ),
        )

    if provider == "moonshine":
        from pipecat.services.moonshine.stt import MoonshineSTTService

        return MoonshineSTTService(settings=MoonshineSTTService.Settings(model="medium-streaming"))

    raise ValueError(f"Unknown STT provider: {provider}")


def stt_provides_turn_detection(provider: STTProvider) -> bool:
    return provider == "deepgram_flux"


def build_vad(config: HALConfig) -> SileroVADAnalyzer:
    return SileroVADAnalyzer(
        params=VADParams(
            confidence=config.turn.vad_confidence,
            stop_secs=config.turn.vad_stop_secs,
            min_volume=config.turn.vad_min_volume,
        )
    )


def build_user_turn_strategies(config: HALConfig, *, provider: STTProvider | None = None) -> UserTurnStrategies | None:
    """Local turn-taking strategies; ``None`` lets a self-detecting STT (Flux) drive turns."""
    provider = provider or config.stt.provider
    if stt_provides_turn_detection(provider):
        return None
    if not config.turn.smart_turn_enabled:
        return UserTurnStrategies()  # VAD + speech-timeout defaults
    analyzer = LocalSmartTurnAnalyzerV3(
        cpu_count=config.turn.smart_turn_cpu_count,
        params=SmartTurnParams(stop_secs=config.turn.smart_turn_stop_secs),
    )
    return UserTurnStrategies(stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=analyzer)])
