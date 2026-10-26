"""Camera capture with a background thread (Pi Camera via picamera2, or OpenCV)."""

from __future__ import annotations

import base64
import threading
import time
from typing import Any

import cv2
import numpy as np
from loguru import logger

from hal.config import VisionConfig

try:
    from picamera2 import Picamera2

    PICAMERA2_AVAILABLE = True
except ImportError:
    Picamera2 = None
    PICAMERA2_AVAILABLE = False


class Camera:
    def __init__(self, config: VisionConfig):
        self.config = config
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._device: Any = None
        self.camera_type = config.camera_type if (config.camera_type != "picamera2" or PICAMERA2_AVAILABLE) else "opencv"
        if config.camera_type == "picamera2" and not PICAMERA2_AVAILABLE:
            logger.warning("picamera2 not available; falling back to OpenCV camera")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, name="hal-camera", daemon=True)
        self._thread.start()
        logger.info(f"Camera started ({self.camera_type}, {self.config.width}x{self.config.height}@{self.config.fps})")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def latest_frame(self) -> np.ndarray | None:
        """Most recent BGR frame, or None."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    # ---- encoders -----------------------------------------------------------

    def jpeg(self, *, size: int | None = None, quality: int = 80) -> bytes | None:
        frame = self.latest_frame()
        if frame is None:
            return None
        if size:
            frame = _center_square(frame, size)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return buf.tobytes() if ok else None

    def jpeg_base64(self, *, max_width: int = 800, quality: int = 85) -> str | None:
        frame = self.latest_frame()
        if frame is None:
            return None
        height, width = frame.shape[:2]
        if width > max_width:
            scale = max_width / width
            frame = cv2.resize(frame, (max_width, int(height * scale)))
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return base64.b64encode(buf.tobytes()).decode("ascii") if ok else None

    # ---- capture loops ----------------------------------------------------------

    def _capture_loop(self) -> None:
        try:
            if self.camera_type == "picamera2":
                self._loop_picamera2()
            else:
                self._loop_opencv()
        except Exception as exc:
            logger.exception(f"Camera loop crashed: {exc}")
        finally:
            self._release()

    def _loop_picamera2(self) -> None:
        self._device = Picamera2()
        config = self._device.create_preview_configuration(
            main={"format": "RGB888", "size": (self.config.width, self.config.height)}, buffer_count=4
        )
        self._device.configure(config)
        self._device.start()
        interval = 1.0 / max(self.config.fps, 1)
        while self._running:
            frame = self._device.capture_array("main")
            if frame is not None:
                with self._lock:
                    self._frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            time.sleep(interval)

    def _loop_opencv(self) -> None:
        self._device = cv2.VideoCapture(self.config.camera_index)
        if not self._device.isOpened():
            logger.error(f"Cannot open camera index {self.config.camera_index}")
            return
        self._device.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        self._device.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        self._device.set(cv2.CAP_PROP_FPS, self.config.fps)
        interval = 1.0 / max(self.config.fps, 1)
        while self._running:
            ok, frame = self._device.read()
            if ok:
                with self._lock:
                    self._frame = frame
            time.sleep(interval)

    def _release(self) -> None:
        if self._device is None:
            return
        try:
            if self.camera_type == "picamera2":
                self._device.stop()
                self._device.close()
            else:
                self._device.release()
        except Exception as exc:
            logger.warning(f"Camera release error: {exc}")
        self._device = None


def _center_square(frame: np.ndarray, size: int) -> np.ndarray:
    height, width = frame.shape[:2]
    side = min(width, height)
    x0 = (width - side) // 2
    y0 = (height - side) // 2
    return cv2.resize(frame[y0 : y0 + side, x0 : x0 + side], (size, size))


def red_filter(jpeg_bytes: bytes) -> bytes:
    """Tint a JPEG red for the HAL eye display."""
    img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return jpeg_bytes
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    red = np.zeros_like(img)
    red[:, :, 2] = gray
    ok, buf = cv2.imencode(".jpg", red, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else jpeg_bytes
