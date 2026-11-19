"""A tiny real Win32 window with buttons, for UI Automation integration tests."""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WS_OVERLAPPEDWINDOW = 0x00CF0000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_DISABLED = 0x08000000
BS_PUSHBUTTON = 0
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.argtypes = (
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
)
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = (ctypes.POINTER(WNDCLASSW),)
user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
user32.DispatchMessageW.restype = LRESULT
# Without this the 64-bit module handle is truncated to a 32-bit int.
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class Win32TestWindow:
    """Buttons: list of (id, label, enabled). Clicks are recorded in ``clicked``."""

    _counter = 0

    def __init__(self, buttons: list[tuple[int, str, bool]], x: int = 200, y: int = 200):
        self.buttons = buttons
        self.pos = (x, y)
        self.clicked: list[int] = []
        self.hwnd = 0
        self._ready = threading.Event()
        self._proc = WNDPROC(self._wndproc)  # keep a reference!
        Win32TestWindow._counter += 1
        self._class = f"GestureControlTest{Win32TestWindow._counter}"
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND:
            self.clicked.append(wparam & 0xFFFF)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName=self._class, hbrBackground=6)
        user32.RegisterClassW(ctypes.byref(wc))
        x, y = self.pos
        self.hwnd = user32.CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE, self._class, "Gesture Control UIA test",
            WS_OVERLAPPEDWINDOW | WS_VISIBLE, x, y, 520, 140, None, None, hinst, None,
        )
        for i, (bid, label, enabled) in enumerate(self.buttons):
            style = WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | (0 if enabled else WS_DISABLED)
            user32.CreateWindowExW(0, "BUTTON", label, style, 10 + i * 125, 30, 115, 36,
                                   self.hwnd, bid, hinst, None)
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def __enter__(self) -> "Win32TestWindow":
        self._thread.start()
        self._ready.wait(5)
        return self

    def __exit__(self, *exc) -> None:
        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
        self._thread.join(2)
