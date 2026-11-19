"""Activation / pause state machine.

States
------
PAUSED  - hard pause (hotkey or 'p' key). Nothing is executed or armed.
IDLE    - waiting for the arming gesture (dwell mode only).
ARMING  - open palm held still; arming in progress.
ACTIVE  - gestures are executed.

In ``dwell`` mode you arm by holding an open palm still for ``arm_hold_s``.
The controller disarms when the hand leaves the frame for
``disarm_after_lost_s`` or when you hold a fist for ``fist_hold_s``.
"""

from __future__ import annotations

import threading
from enum import Enum

from .config import ActivationConfig
from .types import HandObservation, Pose


class ActivationState(str, Enum):
    PAUSED = "paused"
    IDLE = "idle"
    ARMING = "arming"
    ACTIVE = "active"


class ActivationController:
    def __init__(self, cfg: ActivationConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._paused = cfg.start_paused
        self._armed = cfg.mode == "always"
        self._still_since: float | None = None
        self._fist_since: float | None = None
        self._last_seen: float | None = None
        self.state = ActivationState.PAUSED if self._paused else self._idle_state()
        self.arming_progress = 0.0

    def _idle_state(self) -> ActivationState:
        return ActivationState.ACTIVE if self._armed else ActivationState.IDLE

    # Called from the hotkey thread as well as the main loop.
    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            self._paused = paused

    def toggle_pause(self) -> bool:
        with self._lock:
            self._paused = not self._paused
            return self._paused

    def update(self, obs: HandObservation | None, speed: float, t: float) -> ActivationState:
        self.state = self._update(obs, speed, t)
        return self.state

    def _update(self, obs: HandObservation | None, speed: float, t: float) -> ActivationState:
        cfg = self.cfg
        if obs is not None:
            self._last_seen = t

        if self.paused:
            self._still_since = self._fist_since = None
            self.arming_progress = 0.0
            if cfg.mode == "dwell":
                self._armed = False
            return ActivationState.PAUSED

        if cfg.mode == "always":
            return ActivationState.ACTIVE

        if self._armed:
            lost_for = t - self._last_seen if self._last_seen is not None else 0.0
            if obs is None and lost_for >= cfg.disarm_after_lost_s:
                self._disarm()
            elif obs is not None and obs.pose is Pose.FIST:
                if self._fist_since is None:
                    self._fist_since = t
                if t - self._fist_since >= cfg.fist_hold_s:
                    self._disarm()
            else:
                self._fist_since = None
            return ActivationState.ACTIVE if self._armed else ActivationState.IDLE

        if obs is not None and obs.pose is Pose.OPEN_PALM and speed < cfg.still_speed:
            if self._still_since is None:
                self._still_since = t
            held = t - self._still_since
            self.arming_progress = min(held / cfg.arm_hold_s, 1.0) if cfg.arm_hold_s > 0 else 1.0
            if held >= cfg.arm_hold_s:
                self._armed = True
                self._still_since = None
                self.arming_progress = 0.0
                return ActivationState.ACTIVE
            return ActivationState.ARMING

        self._still_since = None
        self.arming_progress = 0.0
        return ActivationState.IDLE

    def _disarm(self) -> None:
        self._armed = False
        self._fist_since = None
        self._still_since = None
