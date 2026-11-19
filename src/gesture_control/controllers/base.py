"""OS-independent desktop control interface.

The gesture engine and action layer only talk to ``DesktopController``.
``WindowsController`` implements it today; a ``MacOSController`` (Quartz
CGEvent + Accessibility API) can be added without touching the core.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

WHEEL_DELTA = 120  # One classic mouse-wheel notch.

MODIFIERS = {"ctrl", "alt", "shift", "win"}
NAMED_KEYS = {
    "left", "right", "up", "down", "pageup", "pagedown", "home", "end",
    "space", "enter", "tab", "esc", "backspace", "delete", "insert",
    "browser_back", "browser_forward",
} | {f"f{i}" for i in range(1, 25)}
_ALIASES = {
    "control": "ctrl", "escape": "esc", "return": "enter", "pgup": "pageup",
    "pgdn": "pagedown", "pgdown": "pagedown", "del": "delete", "cmd": "win",
    "super": "win", "meta": "win",
}


def parse_combo(combo: str) -> list[str]:
    """Parse e.g. ``"alt+left"`` into normalised key names, validating them."""
    keys = []
    for raw in combo.lower().replace(" ", "").split("+"):
        if not raw:
            raise ValueError(f"Bad key combo '{combo}'")
        key = _ALIASES.get(raw, raw)
        if not (key in MODIFIERS or key in NAMED_KEYS or (len(key) == 1 and key.isalnum())):
            raise ValueError(f"Unknown key '{raw}' in combo '{combo}'")
        keys.append(key)
    if all(k in MODIFIERS for k in keys):
        raise ValueError(f"Key combo '{combo}' has no non-modifier key")
    return keys


class DesktopController(ABC):
    name = "base"

    @abstractmethod
    def scroll(self, wheel_delta: int) -> None:
        """Vertical wheel scroll. Positive = up (away from user), 120 = one notch."""

    @abstractmethod
    def press_combo(self, keys: list[str]) -> None:
        """Press keys in order, then release them in reverse (e.g. ["alt", "left"])."""

    @abstractmethod
    def click(self, x: int, y: int) -> None:
        """Left-click at physical screen coordinates (used from Phase 2)."""

    def close(self) -> None:  # pragma: no cover - optional hook
        pass
