from __future__ import annotations

import logging

from .base import DesktopController

log = logging.getLogger(__name__)


class DryRunController(DesktopController):
    """Logs actions instead of performing them. Safe for tuning thresholds."""

    name = "dry-run"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def scroll(self, wheel_delta: int) -> None:
        self.calls.append(("scroll", wheel_delta))
        log.debug("[dry-run] scroll %+d", wheel_delta)

    def press_combo(self, keys: list[str]) -> None:
        self.calls.append(("keys", tuple(keys)))
        log.info("[dry-run] keys %s", "+".join(keys))

    def click(self, x: int, y: int, restore_cursor: bool = False) -> None:
        self.calls.append(("click", x, y))
        log.info("[dry-run] click (%d, %d)", x, y)
