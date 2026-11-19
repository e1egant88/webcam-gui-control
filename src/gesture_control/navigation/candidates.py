"""OS-independent description of on-screen controls that might be Next/Previous."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.right, self.bottom

    def intersects(self, other: "Rect") -> bool:
        return (
            self.left < other.right and other.left < self.right
            and self.top < other.bottom and other.top < self.bottom
        )


class ControlKind(str, Enum):
    BUTTON = "button"
    LINK = "link"
    SPLIT_BUTTON = "split_button"
    MENU_ITEM = "menu_item"
    TEXT = "text"  # found by OCR on a screenshot; role unknown
    OTHER = "other"


@dataclass(frozen=True)
class UICandidate:
    name: str
    kind: ControlKind
    rect: Rect
    enabled: bool = True
    offscreen: bool = False
    automation_id: str = ""
    class_name: str = ""
    help_text: str = ""
    invokable: bool = False
    # Backend-specific handle (e.g. a UIA element). Not used by scoring.
    handle: Any = field(default=None, compare=False, repr=False)

    def describe(self) -> str:
        label = self.name or self.automation_id or "<unnamed>"
        return f"'{label}' ({self.kind.value} at {self.rect.center[0]},{self.rect.center[1]})"
