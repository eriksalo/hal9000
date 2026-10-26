"""Face detection and recognition (dlib via the face-recognition library)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np
from loguru import logger

try:
    import face_recognition

    FACE_RECOGNITION_AVAILABLE = True
except ImportError:
    face_recognition = None
    FACE_RECOGNITION_AVAILABLE = False

FaceLocation = tuple[int, int, int, int]  # top, right, bottom, left
UNKNOWN = "Unknown"


class FaceRecognizer:
    def __init__(self, database_path: Path, *, tolerance: float = 0.6):
        self.database_path = database_path
        self.tolerance = tolerance
        self._known: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        if not FACE_RECOGNITION_AVAILABLE:
            logger.warning("face_recognition not installed; faces will never be recognized")
        self.load()

    # ---- database --------------------------------------------------------------

    def load(self) -> None:
        if not self.database_path.exists():
            logger.info(f"No face database at {self.database_path}; starting empty")
            return
        try:
            data = json.loads(self.database_path.read_text(encoding="utf-8"))
            self._known = {name: np.asarray(enc, dtype=np.float64) for name, enc in data.items()}
            logger.info(f"Loaded {len(self._known)} known faces")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.error(f"Cannot load face database: {exc}")

    def save(self) -> None:
        with self._lock:
            data = {name: enc.tolist() for name, enc in self._known.items()}
        self.database_path.write_text(json.dumps(data), encoding="utf-8")

    def register(self, name: str, encoding: np.ndarray) -> None:
        with self._lock:
            self._known[name] = encoding
        self.save()
        logger.info(f"Registered face for {name}")

    def known_names(self) -> list[str]:
        with self._lock:
            return list(self._known)

    # ---- recognition ---------------------------------------------------------------

    def detect(self, frame_bgr: np.ndarray) -> list[tuple[np.ndarray, FaceLocation]]:
        if not FACE_RECOGNITION_AVAILABLE:
            return []
        rgb = np.ascontiguousarray(frame_bgr[:, :, ::-1])
        locations = face_recognition.face_locations(rgb)
        encodings = face_recognition.face_encodings(rgb, locations)
        return list(zip(encodings, locations))

    def identify(self, encoding: np.ndarray) -> str:
        with self._lock:
            if not self._known:
                return UNKNOWN
            names = list(self._known)
            vectors = list(self._known.values())
        distances = face_recognition.face_distance(vectors, encoding)
        best = int(np.argmin(distances))
        return names[best] if distances[best] <= self.tolerance else UNKNOWN

    def recognize(self, frame_bgr: np.ndarray) -> list[tuple[str, FaceLocation, np.ndarray]]:
        """Return ``(name, location, encoding)`` for every face in the frame."""
        return [(self.identify(enc), loc, enc) for enc, loc in self.detect(frame_bgr)]
