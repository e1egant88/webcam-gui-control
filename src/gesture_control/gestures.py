"""Temporal swipe detection from a stream of palm positions.

Pure logic: feed it ``HandObservation`` objects (with timestamps) and it returns
``GestureEvent`` objects. It never reads the clock, so it is fully testable.

How a swipe is recognised
-------------------------
1. Only an open palm is tracked. A fist, another pose or a lost hand clears
   all history, so moving a closed hand never does anything.
2. The palm position is smoothed (EMA) and kept in a short sliding window.
3. Movement is the displacement from the oldest to newest sample in the window,
   divided by the palm size, so thresholds work at any distance from camera.
4. A swipe fires when, along the dominant axis, the displacement is long
   enough, fast enough, and clearly dominant over the other axis.

Guards against accidental and repeated triggers
-----------------------------------------------
* settle: ignore motion just after the hand appears/opens (entering frame).
* cooldown: after an event, nothing fires for a short time.
* re-arm: after an event, the hand must slow down or reverse before another
  event can fire, so one long stroke never fires twice.
* return-stroke suppression: for a while after an event, the opposite
  direction is ignored, so bringing the hand back does not undo the action.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from .config import GestureConfig
from .types import Gesture, GestureEvent, HandObservation, MotionDiagnostics, Pose

# Lower bound for palm size, avoids blow-ups when landmarks collapse.
MIN_PALM_SIZE = 0.03
# Instantaneous speed (palm sizes / s) below which the hand counts as "slowed down".
REARM_SPEED = 1.2


@dataclass
class _Sample:
    t: float
    x: float
    y: float


class GestureDetector:
    def __init__(self, cfg: GestureConfig):
        self.cfg = cfg
        self._samples: deque[_Sample] = deque()
        self._pos: tuple[float, float] | None = None
        self._size: float = 0.0
        self._tracking_since: float | None = None
        self._cooldown_until = -math.inf
        self._last_event: GestureEvent | None = None
        self._rearmed = True
        #: Smoothed instantaneous palm speed in palm sizes / second.
        self.speed = 0.0
        self.diagnostics = MotionDiagnostics()

    # ------------------------------------------------------------------ state
    @property
    def last_event(self) -> GestureEvent | None:
        return self._last_event

    def reset(self, reason: str = "") -> None:
        """Forget the current trajectory (keeps cooldown / last-event memory)."""
        self._samples.clear()
        self._pos = None
        self._tracking_since = None
        self.speed = 0.0
        self.diagnostics = MotionDiagnostics(blocked_reason=reason)

    def _restart_from_last(self) -> None:
        if self._samples:
            last = self._samples[-1]
            self._samples.clear()
            self._samples.append(last)

    # ----------------------------------------------------------------- update
    def update(self, obs: HandObservation | None) -> GestureEvent | None:
        if obs is None:
            self.reset("no hand")
            return None
        if obs.pose is not Pose.OPEN_PALM:
            self.reset(f"pose: {obs.pose.value}")
            return None

        cfg = self.cfg
        t = obs.timestamp
        a = cfg.smoothing_alpha

        if self._pos is None:
            self._pos = (obs.palm_x, obs.palm_y)
            self._size = obs.palm_size
            self._tracking_since = t
            self._samples.clear()
        else:
            px, py = self._pos
            self._pos = (a * obs.palm_x + (1 - a) * px, a * obs.palm_y + (1 - a) * py)
            # Palm size changes slowly; smooth it harder than position.
            self._size = 0.2 * obs.palm_size + 0.8 * self._size

        size = max(self._size, MIN_PALM_SIZE)
        x, y = self._pos

        # Instantaneous velocity, used for re-arming and dwell detection.
        vx = vy = 0.0
        if self._samples:
            prev = self._samples[-1]
            dt = t - prev.t
            if dt <= 0:
                return None  # duplicate / out-of-order timestamp
            vx = (x - prev.x) / size / dt
            vy = (y - prev.y) / size / dt
            self.speed = 0.5 * self.speed + 0.5 * math.hypot(vx, vy)

        self._samples.append(_Sample(t, x, y))
        while len(self._samples) > 1 and t - self._samples[0].t > cfg.window_s:
            self._samples.popleft()

        # Re-arm once the hand has slowed down or reversed along the last axis.
        if not self._rearmed and self._last_event is not None:
            ev = self._last_event
            axis_v = vy if ev.gesture.is_vertical else vx
            if self.speed < REARM_SPEED or axis_v * _axis_sign(ev) < 0:
                self._rearmed = True

        assert self._tracking_since is not None
        if t - self._tracking_since < cfg.settle_s:
            self.diagnostics = MotionDiagnostics(blocked_reason="settling")
            self._restart_from_last()
            return None

        if t < self._cooldown_until or not self._rearmed:
            reason = "cooldown" if t < self._cooldown_until else "waiting to re-arm"
            self.diagnostics = MotionDiagnostics(blocked_reason=reason)
            # Don't let motion during cooldown count towards the next swipe.
            self._restart_from_last()
            return None

        first = _stroke_start(self._samples)
        last = self._samples[-1]
        duration = last.t - first.t
        dx = (last.x - first.x) / size
        dy = (last.y - first.y) / size

        horizontal = abs(dx) >= abs(dy)
        major, minor = (dx, dy) if horizontal else (dy, dx)
        min_dist = cfg.min_distance_horizontal if horizontal else cfg.min_distance_vertical
        speed = abs(major) / duration if duration > 0 else 0.0
        progress = abs(major) / min_dist

        def diag(reason: str = "") -> MotionDiagnostics:
            return MotionDiagnostics(dx, dy, duration, speed, progress, reason)

        if len(self._samples) < cfg.min_samples or duration <= 0:
            self.diagnostics = diag("collecting")
            return None
        if abs(major) < min_dist:
            self.diagnostics = diag()
            return None
        if abs(minor) * cfg.dominance_ratio > abs(major):
            self.diagnostics = diag("diagonal")
            return None
        if speed < cfg.min_speed:
            self.diagnostics = diag("too slow")
            return None

        gesture = self._classify(horizontal, major)

        last_ev = self._last_event
        if (
            last_ev is not None
            and gesture is last_ev.gesture.opposite
            and t - last_ev.timestamp < cfg.return_suppress_s
        ):
            self.diagnostics = diag("return stroke")
            self._restart_from_last()
            return None

        event = GestureEvent(
            gesture=gesture,
            timestamp=t,
            dx=dx,
            dy=dy,
            duration=duration,
            speed=speed,
            strength=speed / cfg.min_speed,
        )
        self._last_event = event
        self._rearmed = False
        self._cooldown_until = t + (
            cfg.cooldown_vertical_s if gesture.is_vertical else cfg.cooldown_horizontal_s
        )
        self._restart_from_last()
        self.diagnostics = diag("fired")
        return event

    def _classify(self, horizontal: bool, major: float) -> Gesture:
        if horizontal:
            g = Gesture.NEXT if major > 0 else Gesture.PREVIOUS
            return g.opposite if self.cfg.invert_horizontal else g
        g = Gesture.SCROLL_DOWN if major > 0 else Gesture.SCROLL_UP
        return g.opposite if self.cfg.invert_vertical else g


def _stroke_start(samples: deque[_Sample]) -> _Sample:
    """Where the current stroke began: the window sample farthest from the latest one.

    Measuring from the turning point (rather than the oldest sample) means a
    stroke that follows a reversal is measured in full, e.g. the down stroke
    right after the hand came back up while "paddling".
    """
    last = samples[-1]
    best, best_d = samples[0], -1.0
    for s in samples:
        d = max(abs(last.x - s.x), abs(last.y - s.y))
        if d > best_d:
            best, best_d = s, d
    return best


def _axis_sign(ev: GestureEvent) -> float:
    """Sign of the physical motion (in image coords) that produced ``ev``."""
    value = ev.dy if ev.gesture.is_vertical else ev.dx
    return 1.0 if value > 0 else -1.0
