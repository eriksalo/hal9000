"""Whisper on the Hailo-10H as a Pipecat segmented STT service.

Uses the hailo-apps speech-recognition pipeline (HailoRT >= 5.2 for the
``small`` variant). VAD segments arrive as WAV; we decode and run them through
the NPU off the event loop.
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import wave
from collections.abc import AsyncGenerator
from pathlib import Path

import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.utils.time import time_now_iso8601

HAILO_APPS_PATH = Path(os.environ.get("HAILO_APPS_PATH", "/home/erik/hailo-apps"))


def _import_hailo():
    if str(HAILO_APPS_PATH) not in sys.path:
        sys.path.insert(0, str(HAILO_APPS_PATH))
    from hailo_apps.python.standalone_apps.speech_recognition.app.hailo_whisper_pipeline import (
        HailoWhisperPipeline,
    )
    from hailo_apps.python.standalone_apps.speech_recognition.app.whisper_hef_registry import HEF_REGISTRY
    from hailo_apps.python.standalone_apps.speech_recognition.common.postprocessing import clean_transcription
    from hailo_apps.python.standalone_apps.speech_recognition.common.preprocessing import (
        improve_input_audio,
        preprocess,
    )

    return HailoWhisperPipeline, HEF_REGISTRY, clean_transcription, improve_input_audio, preprocess


class HailoWhisperSTTService(SegmentedSTTService):
    def __init__(self, *, variant: str = "small", hw_arch: str = "hailo10h", sample_rate: int = 16000, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._variant = variant
        self._hw_arch = hw_arch
        self._pipeline = None
        self._chunk_length = 10
        self._lock = asyncio.Lock()
        self._fns = None

    def can_generate_metrics(self) -> bool:
        return True

    @property
    def wants_wav_segments(self) -> bool:
        return False  # raw 16-bit PCM straight into the mel preprocessor

    async def _ensure_pipeline(self) -> bool:
        if self._pipeline is not None:
            return True
        async with self._lock:
            if self._pipeline is not None:
                return True
            try:
                self._fns = await asyncio.to_thread(_import_hailo)
                pipeline_cls, registry, *_ = self._fns
                paths = registry[self._variant][self._hw_arch]
                self._pipeline = await asyncio.to_thread(
                    pipeline_cls, paths["encoder"], paths["decoder"], self._variant, False
                )
                self._chunk_length = self._pipeline.get_model_input_audio_length()
                logger.info(f"Hailo Whisper ready ({self._variant}, {self._chunk_length}s chunks)")
                return True
            except Exception as exc:
                logger.error(f"Hailo Whisper unavailable: {exc}")
                return False

    def _transcribe(self, pcm: np.ndarray) -> str:
        _, _, clean, improve, preprocess = self._fns
        audio = pcm.astype(np.float32) / 32768.0
        improved, start = improve(audio, vad=True)
        if start is None:
            return ""
        mels = preprocess(improved, is_nhwc=True, chunk_length=self._chunk_length, chunk_offset=max(0.0, start - 0.2))
        pieces = []
        for mel in mels:
            self._pipeline.send_data(mel)
            pieces.append(clean(self._pipeline.get_transcription()))
        return " ".join(p for p in pieces if p).strip()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        if not await self._ensure_pipeline():
            yield ErrorFrame(error="Hailo Whisper is not available")
            return
        await self.start_processing_metrics()
        await self.start_ttfb_metrics()
        try:
            text = await asyncio.to_thread(self._transcribe, _wav_or_pcm_to_int16(audio))
        except Exception as exc:
            logger.error(f"Hailo transcription failed: {exc}")
            yield ErrorFrame(error=f"Hailo transcription failed: {exc}")
            return
        finally:
            await self.stop_ttfb_metrics()
            await self.stop_processing_metrics()
        if text:
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), result=None)


def _wav_or_pcm_to_int16(data: bytes) -> np.ndarray:
    if data[:4] == b"RIFF":
        with wave.open(io.BytesIO(data), "rb") as wav:
            frames = wav.readframes(wav.getnframes())
        return np.frombuffer(frames, dtype=np.int16)
    return np.frombuffer(data, dtype=np.int16)
