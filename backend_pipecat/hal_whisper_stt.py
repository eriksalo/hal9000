#!/usr/bin/env python3
"""
Custom Whisper STT Service for HAL-9000

Local speech recognition using OpenAI Whisper or Hailo-accelerated Whisper.
Integrates with Pipecat's STT service interface.
"""

import asyncio
import io
import os
import tempfile
import wave
from typing import AsyncGenerator, Optional

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    AudioRawFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
)
from pipecat.services.ai_services import STTService

# Try to import Whisper implementations
WHISPER_AVAILABLE = False
HAILO_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
    logger.info("OpenAI Whisper available")
except ImportError:
    logger.warning("whisper not available - install with: pip install openai-whisper")

# Check for Hailo Whisper (custom implementation from original backend)
try:
    import sys
    sys.path.insert(0, "/home/erik/hal9000/backend")
    from hailo_transcription_service import HailoTranscriptionService
    HAILO_AVAILABLE = True
    logger.info("Hailo Whisper available")
except ImportError:
    logger.debug("Hailo Whisper not available")


class HALWhisperSTTService(STTService):
    """
    Local Whisper STT service for HAL-9000.

    Supports both CPU-based OpenAI Whisper and Hailo-accelerated Whisper.
    Provides streaming transcription with VAD integration.
    """

    def __init__(
        self,
        *,
        model: str = "base.en",
        use_hailo: bool = False,
        language: str = "en",
        sample_rate: int = 16000,
        **kwargs
    ):
        """
        Initialize Whisper STT service.

        Args:
            model: Whisper model size (tiny, base, small, medium, large)
            use_hailo: Use Hailo-accelerated Whisper if available
            language: Language code
            sample_rate: Audio sample rate
        """
        super().__init__(sample_rate=sample_rate, **kwargs)

        self.model_name = model
        self.use_hailo = use_hailo and HAILO_AVAILABLE
        self.language = language
        self.model = None

        # Audio buffer for accumulating frames
        self.audio_buffer = bytearray()
        self.min_audio_length = sample_rate * 0.5  # 0.5 seconds minimum

        # Initialize model
        self._initialize_model()

    def _initialize_model(self):
        """Load Whisper model."""
        try:
            if self.use_hailo:
                logger.info("Loading Hailo Whisper model")
                self.model = HailoTranscriptionService()
            elif WHISPER_AVAILABLE:
                logger.info(f"Loading OpenAI Whisper model: {self.model_name}")
                self.model = whisper.load_model(self.model_name)
            else:
                raise ImportError("No Whisper implementation available")

            logger.info("Whisper model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """
        Transcribe audio using Whisper.

        Args:
            audio: Raw PCM audio bytes (16-bit, mono)

        Yields:
            TranscriptionFrame with recognized text
        """
        try:
            # Accumulate audio
            self.audio_buffer.extend(audio)

            # Check if we have enough audio to transcribe
            if len(self.audio_buffer) < self.min_audio_length * 2:  # 2 bytes per sample
                return

            # Convert audio buffer to format expected by Whisper
            audio_data = self._prepare_audio()

            if audio_data is None:
                return

            # Run transcription
            if self.use_hailo:
                text = await self._transcribe_hailo(audio_data)
            else:
                text = await self._transcribe_whisper(audio_data)

            # Clear buffer after transcription
            self.audio_buffer.clear()

            # Yield transcription if we got text
            if text and text.strip():
                logger.debug(f"Transcribed: {text}")
                yield TranscriptionFrame(text=text.strip(), user_id="user", timestamp=0)

        except Exception as e:
            logger.error(f"STT error: {e}")
            yield ErrorFrame(f"STT error: {e}")

    def _prepare_audio(self) -> Optional[np.ndarray]:
        """
        Convert audio buffer to format expected by Whisper.

        Returns:
            NumPy array of float32 audio samples, or None if invalid
        """
        try:
            # Convert bytes to numpy array
            audio_array = np.frombuffer(self.audio_buffer, dtype=np.int16)

            # Convert to float32 in range [-1.0, 1.0]
            audio_float = audio_array.astype(np.float32) / 32768.0

            return audio_float

        except Exception as e:
            logger.error(f"Failed to prepare audio: {e}")
            return None

    async def _transcribe_whisper(self, audio: np.ndarray) -> str:
        """
        Transcribe using OpenAI Whisper.

        Args:
            audio: Float32 audio array

        Returns:
            Transcribed text
        """
        try:
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.model.transcribe(
                    audio,
                    language=self.language,
                    fp16=False,  # CPU mode
                )
            )

            return result.get("text", "")

        except Exception as e:
            logger.error(f"Whisper transcription error: {e}")
            return ""

    async def _transcribe_hailo(self, audio: np.ndarray) -> str:
        """
        Transcribe using Hailo Whisper.

        Args:
            audio: Float32 audio array

        Returns:
            Transcribed text
        """
        try:
            # Convert numpy array to WAV file for Hailo service
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

                # Write WAV file
                with wave.open(temp_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(self.sample_rate)

                    # Convert back to int16 for WAV
                    audio_int16 = (audio * 32768.0).astype(np.int16)
                    wav_file.writeframes(audio_int16.tobytes())

            # Transcribe using Hailo service
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.model.transcribe_file,
                temp_path
            )

            # Clean up temp file
            os.unlink(temp_path)

            return result.get("text", "")

        except Exception as e:
            logger.error(f"Hailo transcription error: {e}")
            return ""


class HALVoskSTTService(STTService):
    """
    Vosk STT service for HAL-9000.

    Lightweight alternative to Whisper using Vosk for speech recognition.
    Better for real-time streaming on resource-constrained devices.
    """

    def __init__(
        self,
        *,
        model_path: str = "/home/erik/hal9000/vosk_model/vosk-model-small-en-us-0.15",
        sample_rate: int = 16000,
        **kwargs
    ):
        """
        Initialize Vosk STT service.

        Args:
            model_path: Path to Vosk model directory
            sample_rate: Audio sample rate
        """
        super().__init__(sample_rate=sample_rate, **kwargs)

        self.model_path = model_path
        self.model = None
        self.recognizer = None

        # Initialize Vosk
        self._initialize_model()

    def _initialize_model(self):
        """Load Vosk model."""
        try:
            from vosk import Model, KaldiRecognizer
            import json

            logger.info(f"Loading Vosk model from {self.model_path}")
            self.model = Model(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
            logger.info("Vosk model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load Vosk model: {e}")
            raise

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """
        Transcribe audio using Vosk.

        Args:
            audio: Raw PCM audio bytes (16-bit, mono)

        Yields:
            TranscriptionFrame or InterimTranscriptionFrame
        """
        try:
            # Feed audio to recognizer
            if self.recognizer.AcceptWaveform(audio):
                # Final result
                result = json.loads(self.recognizer.Result())
                text = result.get("text", "")

                if text.strip():
                    logger.debug(f"Vosk transcribed: {text}")
                    yield TranscriptionFrame(text=text.strip(), user_id="user", timestamp=0)
            else:
                # Partial result
                result = json.loads(self.recognizer.PartialResult())
                text = result.get("partial", "")

                if text.strip():
                    logger.debug(f"Vosk partial: {text}")
                    yield InterimTranscriptionFrame(text=text.strip(), user_id="user", timestamp=0)

        except Exception as e:
            logger.error(f"Vosk STT error: {e}")
            yield ErrorFrame(f"STT error: {e}")
