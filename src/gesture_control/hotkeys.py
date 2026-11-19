"""System-wide hotkey (emergency pause) using Win32 ``RegisterHotKey``.

Works while any other application has focus, needs no admin rights and no
third-party keyboard hook.
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable

from .controllers.base import MODIFIERS, parse_combo

log = logging.getLogger(__name__)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
_MOD_BITS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}


def parse_hotkey(combo: str) -> tuple[int, str]:
    keys = parse_combo(combo)
    mods = [k for k in keys if k in MODIFIERS]
    main = [k for k in keys if k not in MODIFIERS]
    if len(main) != 1 or not mods:
        raise ValueError(f"Hotkey '{combo}' needs >=1 modifier and exactly one key")
    bits = MOD_NOREPEAT
    for m in mods:
        bits |= _MOD_BITS[m]
    return bits, main[0]


class GlobalHotkey:
    def __init__(self, combo: str, callback: Callable[[], None]):
        self.combo = combo
        self.callback = callback
        self.modifiers, self.key = parse_hotkey(combo)
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self.registered = False

    def start(self) -> "GlobalHotkey":
        if sys.platform != "win32":
            log.warning("Global hotkey not supported on %s yet", sys.platform)
            return self
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=2.0)
        return self

    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        from .controllers.windows import VK

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32")
        self._thread_id = kernel32.GetCurrentThreadId()
        hotkey_id = 1
        if not user32.RegisterHotKey(None, hotkey_id, self.modifiers, VK[self.key]):
            log.error(
                "Could not register global hotkey %s (error %d) - another app may own it. "
                "Change activation.pause_hotkey in config.toml.",
                self.combo, ctypes.get_last_error(),
            )
            self._ready.set()
            return
        self.registered = True
        log.info("Global pause hotkey: %s", self.combo)
        self._ready.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                    try:
                        self.callback()
                    except Exception:
                        log.exception("Hotkey callback failed")
        finally:
            user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        if self._thread is None or not self._thread_id:
            return
        import ctypes

        ctypes.WinDLL("user32").PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=1.0)
