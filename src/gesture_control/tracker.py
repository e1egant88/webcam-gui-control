"""MediaPipe Hand Landmarker wrapper (Tasks API, VIDEO running mode)."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    RunningMode,
)

from .config import TrackerConfig
from .hand_geometry import observation_from_landmarks
from .types import HandObservation

log = logging.getLogger(__name__)


def ensure_model(cfg: TrackerConfig, base_dir: Path) -> Path:
    path = Path(cfg.model_path)
    if not path.is_absolute():
        path = base_dir / path
    if path.exists():
        return path
    if not cfg.auto_download_model:
        raise FileNotFoundError(
            f"Hand landmarker model not found at {path}. Download it from {cfg.model_url}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading hand landmarker model to %s ...", path)
    tmp = path.with_suffix(".part")
    urllib.request.urlretrieve(cfg.model_url, tmp)
    tmp.replace(path)
    log.info("Model downloaded (%.1f MB)", path.stat().st_size / 1e6)
    return path


class HandTracker:
    def __init__(self, cfg: TrackerConfig, model_path: Path):
        self.cfg = cfg
        options = HandLandmarkerOptions(
            # Pass the bytes rather than the path: avoids MediaPipe path issues
            # with non-ASCII Windows user folders.
            base_options=BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=RunningMode.VIDEO,
            num_hands=1,
            min_hand_detection_confidence=cfg.min_detection_confidence,
            min_hand_presence_confidence=cfg.min_presence_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        self._landmarker = HandLandmarker.create_from_options(options)
        self._last_ts_ms = -1

    def process(self, frame_bgr: np.ndarray, timestamp: float) -> HandObservation | None:
        """Detect a hand in ``frame_bgr``. ``timestamp`` is monotonic seconds."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # VIDEO mode requires strictly increasing integer timestamps.
        ts_ms = max(int(timestamp * 1000), self._last_ts_ms + 1)
        self._last_ts_ms = ts_ms
        result = self._landmarker.detect_for_video(image, ts_ms)
        if not result.hand_landmarks:
            return None
        lms = [(lm.x, lm.y) for lm in result.hand_landmarks[0]]
        return observation_from_landmarks(
            lms,
            timestamp=timestamp,
            aspect=w / h,
            extension_ratio=self.cfg.finger_extension_ratio,
            open_min_fingers=self.cfg.open_palm_min_fingers,
            fist_max_fingers=self.cfg.fist_max_fingers,
        )

    def close(self) -> None:
        self._landmarker.close()
