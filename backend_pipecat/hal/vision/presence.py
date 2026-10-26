"""Async presence monitor: camera -> faces -> tracker -> callbacks."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import numpy as np
from loguru import logger

from hal.config import VisionConfig
from hal.vision.camera import Camera
from hal.vision.faces import UNKNOWN, FaceRecognizer
from hal.vision.tracker import PersonTracker, PresenceEvent

PresenceCallback = Callable[[PresenceEvent], Awaitable[None]]


class PresenceMonitor:
    def __init__(self, config: VisionConfig, *, camera: Camera, recognizer: FaceRecognizer):
        self.config = config
        self.camera = camera
        self.recognizer = recognizer
        self.tracker = PersonTracker(
            presence_threshold=config.presence_threshold_secs,
            departure_threshold=config.departure_threshold_secs,
            greeting_cooldown=config.greeting_cooldown_secs,
        )
        self._callbacks: list[PresenceCallback] = []
        self._task: asyncio.Task | None = None
        self._last_unknown_encoding: np.ndarray | None = None

    def on_presence(self, callback: PresenceCallback) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        self.camera.start()
        self._task = asyncio.create_task(self._loop(), name="hal-presence")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.camera.stop()

    @property
    def last_unknown_encoding(self) -> np.ndarray | None:
        """Encoding of the most recently seen unknown face (for registration)."""
        return self._last_unknown_encoding

    async def _loop(self) -> None:
        logger.info("Presence monitor running")
        while True:
            try:
                frame = self.camera.latest_frame()
                if frame is None:
                    await asyncio.sleep(0.25)
                    continue
                results = await asyncio.to_thread(self.recognizer.recognize, frame)
                detections = []
                for name, location, encoding in results:
                    detections.append((name, location))
                    if name == UNKNOWN:
                        self._last_unknown_encoding = encoding
                event = self.tracker.update(detections)
                if event:
                    logger.info(f"Presence: arrived={event.arrived} departed={event.departed}")
                    for callback in self._callbacks:
                        try:
                            await callback(event)
                        except Exception as exc:
                            logger.exception(f"Presence callback failed: {exc}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception(f"Presence loop error: {exc}")
                await asyncio.sleep(1.0)
            await asyncio.sleep(self.config.detection_interval_secs)
