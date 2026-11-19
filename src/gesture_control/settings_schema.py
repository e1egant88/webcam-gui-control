"""What the settings window shows: labels, help, ranges, live vs restart.

Kept separate from the config dataclasses so config.py stays plain. A test
checks every entry against the real config fields.

``live=True``: the running app reads the value every frame (it is applied by
mutating the live config objects in place). ``live=False``: the value is read
once at start-up, so the app offers a restart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Spec:
    section: str  # "" for top-level AppConfig fields
    key: str
    label: str
    help: str = ""
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    decimals: int = 2
    choices: tuple[str, ...] = ()
    live: bool = True
    suffix: str = ""


TABS: dict[str, list[Spec]] = {
    "Gestures": [
        Spec("gestures", "min_distance_vertical", "Scroll stroke length", "How far (in palm sizes) an up/down stroke must travel.", 0.3, 4.0, 0.1, 1, suffix=" palms"),
        Spec("gestures", "min_distance_horizontal", "Swipe length (next/prev)", "How far a left/right swipe must travel.", 0.3, 5.0, 0.1, 1, suffix=" palms"),
        Spec("gestures", "min_speed", "Minimum speed", "Strokes slower than this are ignored. Raise it if you get accidental triggers.", 0.5, 15.0, 0.5, 1, suffix=" palms/s"),
        Spec("gestures", "window_s", "Stroke time window", "A stroke must happen within this time.", 0.15, 1.0, 0.05, 2, suffix=" s"),
        Spec("gestures", "dominance_ratio", "Straightness", "Main direction must be this many times larger than the other. Higher = diagonal moves are ignored more.", 1.0, 4.0, 0.1, 1, suffix=" x"),
        Spec("gestures", "smoothing_alpha", "Responsiveness", "1.0 = raw (jittery, instant); lower = smoother but laggier.", 0.1, 1.0, 0.05, 2),
        Spec("gestures", "cooldown_vertical_s", "Pause between scrolls", "", 0.0, 2.0, 0.05, 2, suffix=" s"),
        Spec("gestures", "cooldown_horizontal_s", "Pause between next/prev", "", 0.0, 3.0, 0.1, 1, suffix=" s"),
        Spec("gestures", "return_suppress_s", "Ignore return stroke for", "After a gesture, the opposite direction is ignored this long so bringing your hand back does nothing.", 0.0, 2.0, 0.1, 1, suffix=" s"),
        Spec("gestures", "invert_vertical", "Invert scrolling", "Hand down = scroll up."),
        Spec("gestures", "invert_horizontal", "Swap next / previous", "Hand right = previous."),
    ],
    "Activation": [
        Spec("activation", "mode", "Activation", "dwell: hold an open palm still to arm. always: active unless paused.", choices=("dwell", "always")),
        Spec("activation", "arm_hold_s", "Hold still to arm", "", 0.1, 3.0, 0.1, 1, suffix=" s"),
        Spec("activation", "still_speed", "\"Still\" means slower than", "", 0.1, 3.0, 0.1, 1, suffix=" palms/s"),
        Spec("activation", "disarm_after_lost_s", "Disarm when hand gone for", "", 0.2, 10.0, 0.1, 1, suffix=" s"),
        Spec("activation", "fist_hold_s", "Hold fist to disarm", "", 0.1, 3.0, 0.1, 1, suffix=" s"),
        Spec("activation", "pause_hotkey", "Pause hotkey", "Global shortcut, e.g. ctrl+alt+p.", live=False),
    ],
    "Scrolling": [
        Spec("scroll", "notches_per_swipe", "Scroll per stroke", "Mouse-wheel notches per stroke.", 0.5, 20.0, 0.5, 1, suffix=" notches"),
        Spec("scroll", "max_speed_multiplier", "Fast-stroke boost", "Fast strokes scroll up to this many times further.", 1.0, 5.0, 0.1, 1, suffix=" x"),
        Spec("scroll", "smooth", "Smooth scrolling"),
        Spec("scroll", "duration_s", "Smooth scroll duration", "", 0.05, 1.0, 0.05, 2, suffix=" s"),
        Spec("scroll", "high_resolution", "Fine-grained wheel steps", "Turn off if an app ignores small scroll steps."),
    ],
    "Next / Previous": [
        Spec("navigation", "mode", "Left/right swipes", "uia: find and press real Next/Previous buttons (falls back to keys). keys: always send keys. none: do nothing.", choices=("uia", "keys", "none"), live=False),
        Spec("navigation", "fallback_to_keys", "Fall back to keys", "Send the keys below when no clear button is found.", live=False),
        Spec("navigation", "next_keys", "Next keys", "Comma-separated key combos, e.g. right or alt+right.", live=False),
        Spec("navigation", "previous_keys", "Previous keys", "", live=False),
        Spec("navigation", "include_back_forward", "Use Back/Forward buttons", "Treat \"Back\"/\"Forward\" buttons (e.g. browser toolbar) as previous/next.", live=False),
        Spec("navigation", "extra_next_names", "Extra 'next' labels", "Other languages, comma-separated, e.g. weiter, suivant.", live=False),
        Spec("navigation", "extra_previous_names", "Extra 'previous' labels", "", live=False),
        Spec("navigation", "ocr_fallback", "Screenshot (OCR) fallback", "Read button text from the screen when an app has no accessibility info. Local only.", live=False),
        Spec("navigation", "activation_method", "How to press", "auto: accessibility Invoke, else click. invoke / click: only that.", choices=("auto", "invoke", "click"), live=False),
        Spec("navigation", "restore_cursor", "Put mouse back after clicking", live=False),
    ],
    "Overlay": [
        Spec("overlay", "corner", "Position", "", choices=("bottom-right", "bottom-left", "top-right", "top-left")),
        Spec("overlay", "show_camera", "Show camera"),
        Spec("overlay", "opacity", "Background opacity", "", 0.2, 1.0, 0.05, 2),
        Spec("overlay", "highlight_targets", "Outline pressed buttons"),
    ],
    "Camera": [
        Spec("camera", "index", "Camera number", "0 = first camera.", 0, 10, 1, 0, live=False),
        Spec("camera", "mirror", "Mirror image", "Keep on for a normal front-facing webcam."),
        Spec("camera", "width", "Width", "", 160, 1920, 1, 0, live=False, suffix=" px"),
        Spec("camera", "height", "Height", "", 120, 1080, 1, 0, live=False, suffix=" px"),
        Spec("", "dry_run", "Dry run (log only, never press anything)", live=False),
    ],
}


def all_specs() -> list[Spec]:
    return [s for specs in TABS.values() for s in specs]


def check_schema(cfg) -> list[str]:
    """Mismatches between this schema and the config dataclasses (used by tests)."""
    from dataclasses import fields

    problems = []
    for spec in all_specs():
        holder = getattr(cfg, spec.section) if spec.section else cfg
        if spec.key not in {f.name for f in fields(holder)}:
            problems.append(f"{spec.section}.{spec.key}: no such config field")
            continue
        value = getattr(holder, spec.key)
        if spec.choices and value not in spec.choices:
            problems.append(f"{spec.section}.{spec.key}: default {value!r} not in choices")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not spec.choices:
            if spec.minimum is not None and value < spec.minimum:
                problems.append(f"{spec.section}.{spec.key}: default below minimum")
            if spec.maximum is not None and value > spec.maximum:
                problems.append(f"{spec.section}.{spec.key}: default above maximum")
    return problems
