"""Synthetic hand trajectories for deterministic tests."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from gesture_control.types import HandObservation, Pose

FPS = 30
DT = 1 / FPS
PALM = 0.15  # palm size in frame-height units (typical at ~60 cm)


def obs(t: float, x: float, y: float, pose: Pose = Pose.OPEN_PALM, size: float = PALM) -> HandObservation:
    return HandObservation(timestamp=t, palm_x=x, palm_y=y, palm_size=size, pose=pose, extended_fingers=4)


def hold(t0: float, x: float, y: float, seconds: float, pose: Pose = Pose.OPEN_PALM) -> list[HandObservation]:
    n = int(round(seconds * FPS))
    return [obs(t0 + i * DT, x, y, pose) for i in range(n)]


def move(
    t0: float, start: tuple[float, float], end: tuple[float, float], seconds: float,
    pose: Pose = Pose.OPEN_PALM,
) -> list[HandObservation]:
    """Linear move from ``start`` to ``end`` (exclusive of start frame)."""
    n = max(int(round(seconds * FPS)), 1)
    (x0, y0), (x1, y1) = start, end
    return [
        obs(t0 + i * DT, x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n, pose)
        for i in range(1, n + 1)
    ]


class Script:
    """Builds a continuous trajectory: ``Script().hold(0.5).move(dx, dy, 0.2)``."""

    def __init__(self, x: float = 0.65, y: float = 0.5, t: float = 0.0):
        self.x, self.y, self.t = x, y, t
        self.frames: list[HandObservation | None] = []

    def hold(self, seconds: float, pose: Pose = Pose.OPEN_PALM) -> "Script":
        frames = hold(self.t + DT, self.x, self.y, seconds, pose)
        self.frames += frames
        self.t += len(frames) * DT
        return self

    def move(self, dx_palms: float, dy_palms: float, seconds: float, pose: Pose = Pose.OPEN_PALM) -> "Script":
        end = (self.x + dx_palms * PALM, self.y + dy_palms * PALM)
        frames = move(self.t, (self.x, self.y), end, seconds, pose)
        self.frames += frames
        self.x, self.y = end
        self.t += len(frames) * DT
        return self

    def gone(self, seconds: float) -> "Script":
        n = int(round(seconds * FPS))
        self.frames += [None] * n
        self.t += n * DT
        return self

    def __iter__(self) -> Iterator[HandObservation | None]:
        return iter(self.frames)


def run(detector, frames: Iterable[HandObservation | None]):
    return [e for e in (detector.update(f) for f in frames) if e is not None]
