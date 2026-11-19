"""Plain data types shared between the tracker, gesture engine and action layer.

Nothing in here depends on OpenCV, MediaPipe or the operating system, so the
gesture logic can be unit-tested with synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Pose(str, Enum):
    OPEN_PALM = "open_palm"
    FIST = "fist"
    OTHER = "other"


class Gesture(str, Enum):
    SCROLL_UP = "scroll_up"
    SCROLL_DOWN = "scroll_down"
    PREVIOUS = "previous"
    NEXT = "next"

    @property
    def is_vertical(self) -> bool:
        return self in (Gesture.SCROLL_UP, Gesture.SCROLL_DOWN)

    @property
    def opposite(self) -> "Gesture":
        return _OPPOSITE[self]


_OPPOSITE = {
    Gesture.SCROLL_UP: Gesture.SCROLL_DOWN,
    Gesture.SCROLL_DOWN: Gesture.SCROLL_UP,
    Gesture.PREVIOUS: Gesture.NEXT,
    Gesture.NEXT: Gesture.PREVIOUS,
}


@dataclass(frozen=True)
class HandObservation:
    """One detected hand in one frame.

    Coordinates are in *aspect-corrected frame units*: y is the fraction of the
    frame height (0 = top, 1 = bottom) and x is scaled by the same unit, so a
    distance of 0.1 means the same physical size horizontally and vertically.
    ``x`` grows to the right *of the displayed image* (i.e. after mirroring, if
    mirroring is enabled), ``y`` grows downwards.
    """

    timestamp: float
    palm_x: float
    palm_y: float
    # Wrist -> middle-finger MCP distance, same units as palm_x/palm_y. Used to
    # normalise movement so thresholds don't depend on distance from camera.
    palm_size: float
    pose: Pose
    extended_fingers: int = 0
    # Optional raw landmarks (normalised image coords) for visualisation only.
    landmarks: tuple[tuple[float, float], ...] = field(default=(), compare=False, repr=False)


@dataclass(frozen=True)
class GestureEvent:
    gesture: Gesture
    timestamp: float
    # Displacement over the detection window, in palm-size units.
    dx: float
    dy: float
    duration: float
    # Peak-ish speed along the dominant axis, in palm-sizes per second.
    speed: float
    # speed / min_speed, >= 1.0. Used to scale scroll distance.
    strength: float


@dataclass(frozen=True)
class MotionDiagnostics:
    """Live numbers exposed for the debug view and threshold tuning."""

    dx: float = 0.0
    dy: float = 0.0
    duration: float = 0.0
    speed: float = 0.0
    # 0..1+ progress of the dominant axis towards ``min_distance``.
    progress: float = 0.0
    blocked_reason: str = ""
