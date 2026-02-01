#!/usr/bin/env python3
"""
Custom Piper TTS Service for HAL-9000 Voice

Integrates Piper TTS with the HAL-9000 voice model into Pipecat's pipeline.
Based on Pipecat's TTS service interface.
"""

import asyncio
import io
import json
import wave
from typing import AsyncGenerator, Optional

from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.ai_services import TTSService

try:
    from piper.voice import PiperVoice
    PIPER_AVAILABLE = True
except ImportError:
    PIPER_AVAILABLE = False
    logger.warning("piper-tts not available - install with: pip install piper-tts")


class HALPiperTTSService(TTSService):
    """
    HAL 9000 Text-to-Speech service using Piper with HAL voice model.

    This service synthesizes text using the HAL-9000 voice model and
    outputs audio frames compatible with Pipecat's pipeline.
    """

    def __init__(
        self,
        *,
        model_path: str = "/home/erik/hal9000/hal_9000_model/hal.onnx",
        config_path: Optional[str] = None,
        sample_rate: int = 22050,
        **kwargs
    ):
        """
        Initialize HAL Piper TTS service.

        Args:
            model_path: Path to HAL-9000 ONNX model
            config_path: Path to model config JSON (auto-detected if None)
            sample_rate: Audio sample rate (22050 for HAL model)
        """
        super().__init__(**kwargs)

        if not PIPER_AVAILABLE:
            raise ImportError("piper-tts not installed")

        self.model_path = model_path
        self.config_path = config_path or f"{model_path}.json"
        self.sample_rate = sample_rate

        # Load Piper voice model
        try:
            logger.info(f"Loading HAL-9000 voice model from {self.model_path}")
            self.voice = PiperVoice.load(self.model_path, config_path=self.config_path)
            logger.info("HAL-9000 voice model loaded successfully")

            # Verify sample rate
            if self.voice.config.sample_rate != self.sample_rate:
                logger.warning(
                    f"Model sample rate {self.voice.config.sample_rate} "
                    f"differs from configured {self.sample_rate}"
                )
                self.sample_rate = self.voice.config.sample_rate

        except Exception as e:
            logger.error(f"Failed to load HAL voice model: {e}")
            raise

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """
        Synthesize text to speech using HAL-9000 voice.

        Args:
            text: Text to synthesize

        Yields:
            TTSStartedFrame, TTSAudioRawFrame(s), TTSStoppedFrame
        """
        try:
            logger.debug(f"HAL synthesizing: {text}")

            # Signal TTS started
            yield TTSStartedFrame()

            # Synthesize audio
            # Piper returns PCM audio data as bytes
            audio_stream = io.BytesIO()

            # Synthesize with Piper
            # The synthesize_stream_raw method yields audio chunks
            with wave.open(audio_stream, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(self.sample_rate)

                # Synthesize and write audio
                for audio_bytes in self.voice.synthesize_stream_raw(text):
                    wav_file.writeframes(audio_bytes)

                    # Also yield audio frame for pipeline
                    # Convert to format expected by Pipecat
                    yield TTSAudioRawFrame(
                        audio=audio_bytes,
                        sample_rate=self.sample_rate,
                        num_channels=1
                    )

            logger.debug(f"HAL synthesis complete: {len(audio_stream.getvalue())} bytes")

            # Signal TTS completed
            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"HAL TTS error: {e}")
            yield ErrorFrame(f"TTS error: {e}")

    async def say(self, text: str):
        """
        Convenience method to synthesize and push audio frames.

        Args:
            text: Text to synthesize
        """
        async for frame in self.run_tts(text):
            await self.push_frame(frame)


class HALPiperTTSServiceHTTP(TTSService):
    """
    HAL 9000 TTS service using HTTP endpoint.

    Alternative implementation that calls the existing Flask /api/synthesize endpoint.
    Useful if the Piper model is already served via HTTP.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:5000",
        sample_rate: int = 22050,
        **kwargs
    ):
        """
        Initialize HAL Piper TTS HTTP service.

        Args:
            base_url: Base URL of Flask backend
            sample_rate: Audio sample rate
        """
        super().__init__(sample_rate=sample_rate, **kwargs)

        self.base_url = base_url.rstrip("/")
        self.session = None

    async def start(self):
        """Initialize HTTP session."""
        import aiohttp
        self.session = aiohttp.ClientSession()
        logger.info(f"HAL TTS HTTP service connected to {self.base_url}")

    async def stop(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        """
        Synthesize text via HTTP endpoint.

        Args:
            text: Text to synthesize

        Yields:
            TTSStartedFrame, TTSAudioRawFrame(s), TTSStoppedFrame
        """
        try:
            logger.debug(f"HAL HTTP synthesizing: {text}")

            # Signal TTS started
            yield TTSStartedFrame()

            # Call Flask API
            async with self.session.post(
                f"{self.base_url}/api/synthesize",
                json={"text": text},
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"HTTP {response.status}: {error_text}")

                # Read audio data
                audio_data = await response.read()

                # Parse WAV data to extract PCM
                # Skip WAV header (44 bytes) to get raw PCM
                pcm_data = audio_data[44:]

                # Yield audio frame
                # Note: May need to chunk this for large audio
                chunk_size = 4096
                for i in range(0, len(pcm_data), chunk_size):
                    chunk = pcm_data[i:i+chunk_size]
                    yield TTSAudioRawFrame(
                        audio=chunk,
                        sample_rate=self.sample_rate,
                        num_channels=1
                    )

            logger.debug(f"HAL HTTP synthesis complete: {len(audio_data)} bytes")

            # Signal TTS completed
            yield TTSStoppedFrame()

        except Exception as e:
            logger.error(f"HAL TTS HTTP error: {e}")
            yield ErrorFrame(f"TTS error: {e}")

    async def say(self, text: str):
        """
        Convenience method to synthesize and push audio frames.

        Args:
            text: Text to synthesize
        """
        async for frame in self.run_tts(text):
            await self.push_frame(frame)
