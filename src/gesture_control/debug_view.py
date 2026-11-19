"""OpenCV debug window: camera feed, landmarks, trail, state and tuning numbers."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from .activation import ActivationState
from .config import AppConfig
from .types import HandObservation, MotionDiagnostics, Pose

WINDOW = "Gesture Control (q quit, p pause)"

# (start, end) landmark pairs for the hand skeleton.
CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
)

STATE_COLORS = {
    ActivationState.PAUSED: (80, 80, 200),
    ActivationState.IDLE: (160, 160, 160),
    ActivationState.ARMING: (0, 200, 255),
    ActivationState.ACTIVE: (80, 200, 80),
}


@dataclass
class Frame:
    image: np.ndarray
    obs: HandObservation | None
    state: ActivationState
    arming_progress: float
    diag: MotionDiagnostics
    last_action: str
    last_action_age: float
    fps: float
    controller_name: str


class DebugView:
    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._trail: deque[tuple[int, int]] = deque(maxlen=max(cfg.debug.trail_length, 2))
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, cfg.camera.width, cfg.camera.height)
        if cfg.debug.window_always_on_top:
            try:
                cv2.setWindowProperty(WINDOW, cv2.WND_PROP_TOPMOST, 1)
            except cv2.error:
                pass

    def render(self, f: Frame) -> int:
        """Draw and show ``f``; return the pressed key (or -1)."""
        img = f.image.copy()
        h, w = img.shape[:2]
        aspect = w / h

        if f.obs is not None:
            if self.cfg.debug.draw_landmarks and f.obs.landmarks:
                pts = [(int(x * w), int(y * h)) for x, y in f.obs.landmarks]
                for a, b in CONNECTIONS:
                    cv2.line(img, pts[a], pts[b], (200, 200, 200), 1, cv2.LINE_AA)
                for p in pts:
                    cv2.circle(img, p, 2, (255, 255, 255), -1, cv2.LINE_AA)
            center = (int(f.obs.palm_x / aspect * w), int(f.obs.palm_y * h))
            if f.obs.pose is Pose.OPEN_PALM:
                self._trail.append(center)
            else:
                self._trail.clear()
            pose_color = {Pose.OPEN_PALM: (80, 220, 80), Pose.FIST: (60, 60, 230)}.get(
                f.obs.pose, (0, 200, 255)
            )
            cv2.circle(img, center, 8, pose_color, -1, cv2.LINE_AA)
        else:
            self._trail.clear()

        for i in range(1, len(self._trail)):
            cv2.line(img, self._trail[i - 1], self._trail[i], (255, 180, 0), 2, cv2.LINE_AA)

        # --- status banner
        color = STATE_COLORS[f.state]
        cv2.rectangle(img, (0, 0), (w, 34), (30, 30, 30), -1)
        label = f.state.value.upper()
        if f.state is ActivationState.ARMING:
            label += f" {int(f.arming_progress * 100)}%"
        elif f.state is ActivationState.IDLE and self.cfg.activation.mode == "dwell":
            label += " - hold open palm still to arm"
        _text(img, label, (8, 23), color, 0.6, 2)
        _text(img, f"{f.fps:4.1f} fps  {f.controller_name}", (w - 170, 23), (200, 200, 200), 0.5)

        if f.state is ActivationState.ARMING:
            cv2.rectangle(img, (0, 34), (int(w * f.arming_progress), 38), color, -1)

        # --- tuning numbers
        y = h - 58
        cv2.rectangle(img, (0, y - 18), (w, h), (30, 30, 30), -1)
        pose = f.obs.pose.value if f.obs else "no hand"
        fingers = f" ({f.obs.extended_fingers}/4 fingers)" if f.obs else ""
        _text(img, f"pose: {pose}{fingers}", (8, y), (220, 220, 220), 0.45)
        d = f.diag
        _text(
            img,
            f"dx {d.dx:+.2f}  dy {d.dy:+.2f} palms   speed {d.speed:4.1f}/s   {d.blocked_reason}",
            (8, y + 20), (220, 220, 220), 0.45,
        )
        # Progress bar towards the distance threshold.
        bar_w = int(min(d.progress, 1.0) * (w - 16))
        bar_color = (80, 200, 80) if d.progress >= 1.0 else (0, 170, 255)
        cv2.rectangle(img, (8, y + 30), (w - 8, y + 38), (70, 70, 70), -1)
        cv2.rectangle(img, (8, y + 30), (8 + bar_w, y + 38), bar_color, -1)

        if f.last_action and f.last_action_age < 1.5:
            _text(img, f.last_action, (8, 70), (80, 255, 255), 0.8, 2)

        cv2.imshow(WINDOW, img)
        return cv2.waitKey(1) & 0xFF

    def window_closed(self) -> bool:
        try:
            return cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1
        except cv2.error:
            return True

    def close(self) -> None:
        cv2.destroyAllWindows()


def _text(img: np.ndarray, s: str, org: tuple[int, int], color, scale: float, thick: int = 1) -> None:
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)
