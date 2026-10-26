"""Text-to-speech factory.

Primary: a cloud voice clone of HAL (Cartesia Sonic or ElevenLabs Flash).
Fallback: the local Piper HAL-9000 model served by ``piper.http_server``.
"""

from __future__ import annotations

import aiohttp
from loguru import logger
from pipecat.services.tts_service import TTSService

from hal.config import HALConfig, TTSProvider


def build_tts(config: HALConfig, *, session: aiohttp.ClientSession, provider: TTSProvider | None = None) -> TTSService:
    provider = provider or config.tts.provider
    tts_cfg = config.tts
    logger.info(f"TTS provider: {provider}")

    if provider == "cartesia":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(
            api_key=tts_cfg.cartesia_api_key,
            settings=CartesiaTTSService.Settings(model=tts_cfg.cartesia_model, voice=tts_cfg.cartesia_voice_id),
        )

    if provider == "elevenlabs":
        from pipecat.services.elevenlabs.tts import ElevenLabsTTSService

        return ElevenLabsTTSService(
            api_key=tts_cfg.elevenlabs_api_key,
            settings=ElevenLabsTTSService.Settings(model=tts_cfg.elevenlabs_model, voice=tts_cfg.elevenlabs_voice_id),
        )

    if provider == "piper":
        from pipecat.services.piper.tts import PiperHttpTTSService

        base_url = tts_cfg.piper_url.rstrip("/")
        if not base_url.endswith("/synthesize"):
            base_url += "/synthesize"
        return PiperHttpTTSService(base_url=base_url, aiohttp_session=session, sample_rate=tts_cfg.piper_sample_rate)

    raise ValueError(f"Unknown TTS provider: {provider}")
