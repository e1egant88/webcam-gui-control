"""Turn 21 MediaPipe hand landmarks into palm position, size and pose.

Kept separate from the MediaPipe wrapper so it can be tested without a model.
Landmark indices follow the MediaPipe hand model:
0 wrist; 5/9/13/17 index/middle/ring/pinky MCP; 6/10/14/18 PIP; 8/12/16/20 tips.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from .types import HandObservation, Pose

WRIST = 0
PALM_POINTS = (0, 5, 9, 13, 17)
# (pip, tip) for index, middle, ring, pinky. The thumb is ignored: its
# extension is unreliable from a frontal camera.
FINGERS = ((6, 8), (10, 12), (14, 16), (18, 20))


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def count_extended_fingers(pts: Sequence[tuple[float, float]], ratio: float) -> int:
    wrist = pts[WRIST]
    return sum(1 for pip, tip in FINGERS if _dist(pts[tip], wrist) > _dist(pts[pip], wrist) * ratio)


def observation_from_landmarks(
    landmarks: Sequence[tuple[float, float]],
    timestamp: float,
    aspect: float,
    extension_ratio: float = 1.15,
    open_min_fingers: int = 4,
    fist_max_fingers: int = 0,
) -> HandObservation:
    """Build a ``HandObservation``.

    ``landmarks`` are normalised image coordinates (x, y in 0..1). ``aspect`` is
    frame width / height; x is multiplied by it so both axes share one unit
    (fractions of frame height).
    """
    if len(landmarks) != 21:
        raise ValueError(f"expected 21 landmarks, got {len(landmarks)}")
    pts = [(x * aspect, y) for x, y in landmarks]
    cx = sum(pts[i][0] for i in PALM_POINTS) / len(PALM_POINTS)
    cy = sum(pts[i][1] for i in PALM_POINTS) / len(PALM_POINTS)
    palm_size = _dist(pts[WRIST], pts[9])
    n = count_extended_fingers(pts, extension_ratio)
    if n >= open_min_fingers:
        pose = Pose.OPEN_PALM
    elif n <= fist_max_fingers:
        pose = Pose.FIST
    else:
        pose = Pose.OTHER
    return HandObservation(
        timestamp=timestamp,
        palm_x=cx,
        palm_y=cy,
        palm_size=palm_size,
        pose=pose,
        extended_fingers=n,
        landmarks=tuple(landmarks),
    )
