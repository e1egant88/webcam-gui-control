"""Threaded webcam capture that always hands out the *latest* frame.

Reading frames on a background thread and dropping stale ones keeps latency
low: the gesture engine never processes a frame that has been sitting in the
driver's buffer.
"""

from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from .config import CameraConfig

log = logging.getLogger(__name__)

_BACKENDS = {
    "any": cv2.CAP_ANY,
    "dshow": cv2.CAP_DSHOW,
    "msmf": cv2.CAP_MSMF,
    "avfoundation": cv2.CAP_AVFOUNDATION,
    "v4l2": cv2.CAP_V4L2,
}


class CameraError(RuntimeError):
    pass


class Camera:
    def __init__(self, cfg: CameraConfig):
        self.cfg = cfg
        self._cap: cv2.VideoCapture | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._frame_id = 0

    def start(self) -> "Camera":
        backend = _BACKENDS.get(self.cfg.backend.lower())
        if backend is None:
            raise CameraError(f"Unknown camera backend '{self.cfg.backend}'")
        cap = cv2.VideoCapture(self.cfg.index, backend)
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Could not open camera {self.cfg.index} with backend '{self.cfg.backend}'. "
                "Check the camera index, that no other app is using it, and Windows "
                "Settings > Privacy & security > Camera > 'Let desktop apps access your camera'."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.release()
            raise CameraError("Camera opened but returned no frames")
        h, w = frame.shape[:2]
        log.info(
            "Camera %d opened (%s): %dx%d @ %.0f fps requested %d",
            self.cfg.index, self.cfg.backend, w, h, cap.get(cv2.CAP_PROP_FPS), self.cfg.fps,
        )
        self._cap = cap
        self._publish(frame)
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        return self

    def _publish(self, frame: np.ndarray) -> None:
        if self.cfg.mirror:
            frame = cv2.flip(frame, 1)
        with self._cond:
            self._frame = frame
            self._frame_time = time.monotonic()
            self._frame_id += 1
            self._cond.notify_all()

    def _run(self) -> None:
        assert self._cap is not None
        failures = 0
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok or frame is None:
                failures += 1
                if failures in (1, 30) or failures % 300 == 0:
                    log.warning("Camera read failed (%d in a row)", failures)
                time.sleep(0.01)
                continue
            failures = 0
            self._publish(frame)

    def read(self, last_id: int, timeout: float = 1.0) -> tuple[int, float, np.ndarray] | None:
        """Block until a frame newer than ``last_id`` exists; return (id, time, frame)."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._frame_id > last_id, timeout=timeout):
                return None
            assert self._frame is not None
            return self._frame_id, self._frame_time, self._frame

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "Camera":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
