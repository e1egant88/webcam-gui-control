"""Configuration: typed dataclasses with defaults, optionally overridden from TOML."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)


@dataclass
class CameraConfig:
    index: int = 0
    # "dshow" opens fastest on most Windows webcams; "msmf" or "any" are alternatives.
    backend: str = "dshow"
    width: int = 640
    height: int = 480
    fps: int = 30
    # Flip the image horizontally so it behaves like a mirror: moving your hand
    # to *your* right moves it to the right of the preview. Keep this on for a
    # normal front-facing webcam.
    mirror: bool = True


@dataclass
class TrackerConfig:
    model_path: str = "models/hand_landmarker.task"
    model_url: str = MODEL_URL
    auto_download_model: bool = True
    min_detection_confidence: float = 0.6
    min_presence_confidence: float = 0.6
    min_tracking_confidence: float = 0.5
    # A finger counts as extended when tip-to-wrist distance exceeds
    # pip-to-wrist distance by this ratio.
    finger_extension_ratio: float = 1.15
    # Index/middle/ring/pinky extended count needed for "open palm".
    open_palm_min_fingers: int = 4
    # At most this many extended fingers counts as "fist".
    fist_max_fingers: int = 0


@dataclass
class GestureConfig:
    # Exponential smoothing of the palm position, 0 < alpha <= 1 (1 = no smoothing).
    smoothing_alpha: float = 0.6
    # Sliding window over which a swipe is measured (seconds).
    window_s: float = 0.35
    # Minimum swipe length along the dominant axis, in palm sizes.
    min_distance_vertical: float = 1.0
    min_distance_horizontal: float = 1.4
    # Minimum average speed along the dominant axis, palm sizes / second.
    min_speed: float = 3.0
    # Dominant axis must be this many times larger than the other axis.
    dominance_ratio: float = 1.6
    min_samples: int = 4
    # Ignore movement right after a hand appears or opens (entering the frame).
    settle_s: float = 0.25
    # After any event, ignore everything for this long.
    cooldown_vertical_s: float = 0.25
    cooldown_horizontal_s: float = 0.8
    # After an event, ignore the *opposite* direction for this long, so the
    # hand returning to its start position does not fire the reverse action.
    return_suppress_s: float = 0.7
    invert_vertical: bool = False
    invert_horizontal: bool = False


@dataclass
class ActivationConfig:
    # "dwell": hold an open palm still to arm; "always": active unless paused.
    mode: str = "dwell"
    arm_hold_s: float = 0.6
    # Palm must move slower than this (palm sizes / second) while dwelling.
    still_speed: float = 0.6
    # Disarm when no hand is seen for this long.
    disarm_after_lost_s: float = 1.5
    # Holding a fist this long disarms immediately.
    fist_hold_s: float = 0.4
    # Global hotkey that toggles pause from any application.
    pause_hotkey: str = "ctrl+alt+p"
    start_paused: bool = False


@dataclass
class ScrollConfig:
    # One swipe scrolls this many wheel notches (one notch = 120 wheel units).
    notches_per_swipe: float = 3.0
    # Faster swipes scroll further, up to this multiple.
    max_speed_multiplier: float = 2.5
    smooth: bool = True
    duration_s: float = 0.25
    # Send sub-notch wheel deltas (smoother; most modern apps support it).
    # Set false if an application ignores small wheel deltas.
    high_resolution: bool = True


def _default_blocked_words() -> list[str]:
    from .navigation.scoring import DEFAULT_BLOCKED_WORDS

    return list(DEFAULT_BLOCKED_WORDS)


@dataclass
class NavigationConfig:
    # What left/right swipes do:
    #   "uia":  find a real Next/Previous control in the foreground window with
    #           Windows UI Automation and invoke it (falls back to keys)
    #   "keys": send the key combos below to the foreground window
    #   "none": detect and log only
    mode: str = "uia"
    fallback_to_keys: bool = True
    next_keys: list[str] = field(default_factory=lambda: ["right"])
    previous_keys: list[str] = field(default_factory=lambda: ["left"])
    # --- UIA target selection
    min_score: int = 60
    # Reject when a *different* kind of target scores within this margin.
    ambiguity_margin: int = 15
    # Treat "Back"/"Forward" buttons (e.g. browser toolbar) as previous/next.
    include_back_forward: bool = False
    # Exact extra labels, e.g. other languages: ["weiter", "suivant"].
    extra_next_names: list[str] = field(default_factory=list)
    extra_previous_names: list[str] = field(default_factory=list)
    # Never act on controls whose name contains one of these words.
    blocked_words: list[str] = field(default_factory=_default_blocked_words)
    # Give up (and fall back) if the search takes longer than this.
    search_timeout_s: float = 1.5
    # "auto": UIA Invoke if supported, else mouse click; "invoke"; "click".
    activation_method: str = "auto"
    # Put the mouse cursor back where it was after a click.
    restore_cursor: bool = True


@dataclass
class DebugConfig:
    show_window: bool = True
    window_always_on_top: bool = True
    draw_landmarks: bool = True
    trail_length: int = 20


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    gestures: GestureConfig = field(default_factory=GestureConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    scroll: ScrollConfig = field(default_factory=ScrollConfig)
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    dry_run: bool = False


def _apply(obj: Any, data: dict[str, Any], prefix: str) -> None:
    known = {f.name: f for f in fields(obj)}
    for key, value in data.items():
        if key not in known:
            log.warning("Unknown config key '%s%s' ignored", prefix, key)
            continue
        current = getattr(obj, key)
        if is_dataclass(current):
            if not isinstance(value, dict):
                raise ValueError(f"Config section '{prefix}{key}' must be a table")
            _apply(current, value, f"{prefix}{key}.")
            continue
        if isinstance(current, bool) and not isinstance(value, bool):
            raise ValueError(f"Config '{prefix}{key}' must be true/false")
        if isinstance(current, float) and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        if current is not None and not isinstance(value, type(current)):
            raise ValueError(
                f"Config '{prefix}{key}' must be {type(current).__name__}, got {type(value).__name__}"
            )
        setattr(obj, key, value)


def validate(cfg: AppConfig) -> None:
    g = cfg.gestures
    if not 0 < g.smoothing_alpha <= 1:
        raise ValueError("gestures.smoothing_alpha must be in (0, 1]")
    if g.window_s <= 0 or g.min_speed <= 0:
        raise ValueError("gestures.window_s and gestures.min_speed must be positive")
    if g.dominance_ratio < 1:
        raise ValueError("gestures.dominance_ratio must be >= 1")
    if cfg.activation.mode not in ("dwell", "always"):
        raise ValueError("activation.mode must be 'dwell' or 'always'")
    nav = cfg.navigation
    if nav.mode not in ("uia", "keys", "none"):
        raise ValueError("navigation.mode must be 'uia', 'keys' or 'none'")
    if nav.activation_method not in ("auto", "invoke", "click"):
        raise ValueError("navigation.activation_method must be 'auto', 'invoke' or 'click'")
    if nav.search_timeout_s <= 0:
        raise ValueError("navigation.search_timeout_s must be positive")
    for key in ("next_keys", "previous_keys", "extra_next_names", "extra_previous_names", "blocked_words"):
        if not all(isinstance(v, str) for v in getattr(nav, key)):
            raise ValueError(f"navigation.{key} must be a list of strings")
    if cfg.scroll.max_speed_multiplier < 1:
        raise ValueError("scroll.max_speed_multiplier must be >= 1")


def load_config(path: str | Path | None) -> AppConfig:
    cfg = AppConfig()
    if path is not None:
        p = Path(path)
        if p.exists():
            with p.open("rb") as fh:
                _apply(cfg, tomllib.load(fh), "")
            log.info("Loaded config from %s", p)
        else:
            log.info("Config file %s not found, using defaults", p)
    validate(cfg)
    return cfg
