"""Windows input via ``SendInput`` (ctypes, no extra dependencies).

``SendInput`` lets us send sub-notch wheel deltas, which PyAutoGUI cannot, so
scrolling can be animated smoothly.

Notes
-----
* Wheel events go to the window under the mouse cursor (Windows 10+ default,
  "Scroll inactive windows when I hover over them"); key presses go to the
  foreground window.
* Windows blocks input from a normal process into an elevated (admin) window
  (UIPI). Run this tool elevated only if you need to control admin apps.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

from .base import DesktopController

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("windows controller is only available on Windows")

log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0

ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT
user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
user32.SetCursorPos.restype = wintypes.BOOL

VK = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "backspace": 0x08, "tab": 0x09, "enter": 0x0D, "esc": 0x1B, "space": 0x20,
    "pageup": 0x21, "pagedown": 0x22, "end": 0x23, "home": 0x24,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "insert": 0x2D, "delete": 0x2E,
    "browser_back": 0xA6, "browser_forward": 0xA7,
    **{f"f{i}": 0x6F + i for i in range(1, 25)},
    **{chr(c): c for c in range(ord("0"), ord("9") + 1)},
    **{chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)},
}
# Keys that need KEYEVENTF_EXTENDEDKEY to be distinguished from the numpad.
EXTENDED = {"left", "right", "up", "down", "pageup", "pagedown", "home", "end",
            "insert", "delete", "win", "browser_back", "browser_forward"}


def enable_dpi_awareness() -> None:
    """Make screen coordinates physical pixels on scaled / multi-monitor setups."""
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except AttributeError:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        user32.SetProcessDPIAware()


def _send(*inputs: INPUT) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        err = ctypes.get_last_error()
        log.warning(
            "SendInput sent %d/%d events (error %d). The target window may be elevated "
            "(admin) or input is blocked (e.g. lock screen / UAC prompt).",
            sent, len(inputs), err,
        )


def _mouse(flags: int, data: int = 0) -> INPUT:
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0))


def get_cursor_pos() -> tuple[int, int]:
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def _move_abs(x: int, y: int) -> INPUT:
    """Absolute move in physical pixels across the whole virtual desktop."""
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), 2)
    vh = max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN), 2)
    nx = round((x - vx) * 65535 / (vw - 1))
    ny = round((y - vy) * 65535 / (vh - 1))
    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    return INPUT(type=INPUT_MOUSE, mi=MOUSEINPUT(nx, ny, 0, flags, 0, 0))


def _key(name: str, up: bool) -> INPUT:
    vk = VK[name]
    flags = KEYEVENTF_KEYUP if up else 0
    if name in EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    return INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(vk, scan, flags, 0, 0))


class WindowsController(DesktopController):
    name = "windows"

    def __init__(self) -> None:
        enable_dpi_awareness()

    def scroll(self, wheel_delta: int) -> None:
        if wheel_delta:
            _send(_mouse(MOUSEEVENTF_WHEEL, wheel_delta))

    def press_combo(self, keys: list[str]) -> None:
        unknown = [k for k in keys if k not in VK]
        if unknown:
            raise ValueError(f"No Windows virtual-key code for {unknown}")
        _send(*[_key(k, up=False) for k in keys], *[_key(k, up=True) for k in reversed(keys)])

    def click(self, x: int, y: int, restore_cursor: bool = False) -> None:
        # Move, click and (optionally) move back in ONE SendInput batch so the
        # events are applied in order; a separate SetCursorPos could race.
        events = [_move_abs(x, y), _mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP)]
        if restore_cursor:
            ox, oy = get_cursor_pos()
            events.append(_move_abs(ox, oy))
        _send(*events)
