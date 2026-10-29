"""Local always-on wake-word detection (openWakeWord, ONNX backend).

A lightweight detector runs on the echo-cancelled mic so HAL only spins up the
cloud STT / LLM / TTS session once it hears its wake phrase. Idle costs nothing:
no cloud audio streams while nobody is talking to HAL, and HAL stops answering
conversations that were never addressed to it.

The detector is paused while a conversation is active, so it neither fires on
HAL's own voice nor contends with the pipeline for the microphone.

Cost on the Pi 5: ~5 ms of one core per 80 ms frame with the ONNX runtime.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import numpy as np
from loguru import logger

from hal.config import AudioConfig, WakeConfig
from hal.vision.faces import UNKNOWN

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80 ms @ 16 kHz: openWakeWord's native chunk size

WakeCallback = Callable[[], Awaitable[None]]


class WakeModel(Protocol):
    """The slice of ``openwakeword.Model`` the listener uses (lets tests fake it)."""

    models: dict[str, Any]

    def predict(self, x: np.ndarray, **kwargs: Any) -> dict[str, float]: ...

    def reset(self) -> None: ...


def choose_wake_person(*, known_present: list[str], present: list[str], default_person: str) -> str:
    """Who HAL should assume said the wake phrase.

    A recognised face in view wins; an unrecognised face means HAL should ask
    who they are (and can link the face to the name); nobody in view falls back
    to the configured default partner.
    """
    if known_present:
        return known_present[0]
    if UNKNOWN in present:
        return UNKNOWN
    return default_person


def load_wake_model(config: WakeConfig) -> WakeModel:
    """Load (downloading if needed) the configured openWakeWord model."""
    from openwakeword import Model
    from openwakeword.utils import download_models

    spec = config.model_path
    is_path = spec.endswith(".onnx") or spec.endswith(".tflite") or "/" in spec or "\\" in spec
    try:
        # Stock names need the wake model + the shared feature models; a custom
        # path still needs the feature models, which download_models([]) fetches.
        download_models(model_names=[] if is_path else [spec])
    except Exception as exc:  # offline with everything already cached is fine
        logger.debug(f"openWakeWord model download skipped: {exc}")
    return Model(
        wakeword_models=[spec],
        inference_framework=config.inference_framework,
        vad_threshold=config.vad_threshold,
    )


class WakeWordListener:
    """Background thread that fires an async callback on wake-word detection.

    The model runs on 16 kHz mono int16 audio read straight from the configured
    input device (the PipeWire echo-cancelled source). Detection is debounced by
    ``trigger_frames`` consecutive over-threshold chunks and rate-limited by
    ``refractory_secs``.
    """

    def __init__(
        self,
        config: WakeConfig,
        audio: AudioConfig,
        *,
        on_wake: WakeCallback,
        on_armed_change: Callable[[bool], None] | None = None,
        model: WakeModel | None = None,
    ):
        self.config = config
        self.audio = audio
        self._on_wake = on_wake
        self._on_armed_change = on_armed_change
        self._model: WakeModel | None = model
        self._key = next(iter(model.models)) if model is not None else ""
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._enabled = threading.Event()  # set == actively listening
        self._pa: Any = None
        self._stream: Any = None
        self._above = 0
        self._last_fire = 0.0
        self.last_score = 0.0

    @property
    def phrase(self) -> str:
        return self._key

    @property
    def armed(self) -> bool:
        return self._enabled.is_set() and not self._stop.is_set()

    # ---- lifecycle -------------------------------------------------------------

    async def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        if self._model is None:
            self._model = await asyncio.to_thread(load_wake_model, self.config)
            self._key = next(iter(self._model.models))
        logger.info(f"Wake word ready: '{self._key}' (threshold {self.config.threshold})")
        self._stop.clear()
        self._set_enabled(True)
        self._thread = threading.Thread(target=self._run, name="hal-wake", daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        self._stop.set()
        self._enabled.set()  # unblock any wait so the thread can exit
        if self._thread:
            await asyncio.to_thread(self._thread.join, 5.0)
            self._thread = None
        self._set_enabled(False)

    def pause(self) -> None:
        """Stop listening (releases the mic) while a conversation is active."""
        self._set_enabled(False)

    def resume(self) -> None:
        """Resume listening after a conversation, ignoring any trailing audio."""
        self._above = 0
        self._last_fire = time.monotonic()  # brief refractory so the TTS tail is skipped
        if self._model is not None:
            self._model.reset()
        self._set_enabled(True)

    def _set_enabled(self, value: bool) -> None:
        if value:
            self._enabled.set()
        else:
            self._enabled.clear()
        if self._on_armed_change:
            self._on_armed_change(value and not self._stop.is_set())

    # ---- capture ---------------------------------------------------------------

    def _open_stream(self) -> None:
        import pyaudio  # local import: not needed for tests or non-audio hosts

        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            input_device_index=self.audio.input_device_index,
            frames_per_buffer=FRAME_SAMPLES,
        )

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._enabled.is_set():
                self._close_stream()
                self._enabled.wait(timeout=0.2)
                continue
            if self._stream is None:
                try:
                    self._open_stream()
                    if self._model is not None:
                        self._model.reset()
                except Exception as exc:
                    logger.warning(f"Wake mic open failed ({exc}); retrying")
                    self._close_stream()
                    self._stop.wait(1.0)
                    continue
            try:
                data = self._stream.read(FRAME_SAMPLES, exception_on_overflow=False)
            except Exception as exc:
                logger.warning(f"Wake mic read failed ({exc}); reopening")
                self._close_stream()
                self._stop.wait(0.5)
                continue
            self.process(np.frombuffer(data, dtype=np.int16))
        self._close_stream()
        logger.info("Wake word listener stopped")

    # ---- detection -------------------------------------------------------------

    def process(self, samples: np.ndarray) -> bool:
        """Feed one 80 ms frame; returns True when the wake phrase fired."""
        if self._model is None:
            return False
        scores = self._model.predict(samples)
        score = float(scores.get(self._key, 0.0))
        self.last_score = score
        if score < self.config.threshold:
            self._above = 0
            return False
        self._above += 1
        now = time.monotonic()
        if self._above < self.config.trigger_frames or now - self._last_fire < self.config.refractory_secs:
            return False
        self._above = 0
        self._last_fire = now
        logger.info(f"Wake word '{self._key}' detected (score {score:.2f})")
        self._model.reset()
        self._fire()
        return True

    def _fire(self) -> None:
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._on_wake(), self._loop)
        except Exception as exc:
            logger.exception(f"Wake callback scheduling failed: {exc}")
