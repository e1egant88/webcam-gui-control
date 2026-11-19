"""``--self-test``: check every subsystem without sending any input.

Useful after installing or packaging, and for troubleshooting. Nothing is
clicked, scrolled or typed; the camera is opened briefly. Exit code 0 when
all *required* checks pass; optional ones (camera, hotkey) only warn,
because they can be legitimately busy (e.g. another app uses the camera).
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import AppConfig

log = logging.getLogger(__name__)


@dataclass
class Check:
    name: str
    fn: Callable[[], str]
    required: bool = True


@dataclass
class Result:
    name: str
    ok: bool
    required: bool
    detail: str
    seconds: float


def _in_thread(fn: Callable[[], str]) -> str:
    """Run on a fresh thread (COM apartments, like the real navigation worker)."""
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported to the caller
            box["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(30)
    if t.is_alive():
        raise TimeoutError("timed out after 30 s")
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return str(box.get("value", ""))


def build_checks(cfg: AppConfig, base_dir: Path) -> list[Check]:
    def model() -> str:
        from .tracker import HandTracker, ensure_model

        path = ensure_model(cfg.tracker, base_dir)
        tracker = HandTracker(cfg.tracker, path)
        try:
            out = tracker.process(np.zeros((480, 640, 3), np.uint8), time.monotonic())
        finally:
            tracker.close()
        if out is not None:
            raise AssertionError("detected a hand in a black image")
        return f"MediaPipe hand model loaded ({path.stat().st_size / 1e6:.1f} MB)"

    def input_controller() -> str:
        if sys.platform != "win32":
            raise NotImplementedError("no input controller for this platform yet")
        from .controllers.windows import INPUT, WindowsController
        import ctypes

        WindowsController()
        return f"SendInput ready (INPUT struct {ctypes.sizeof(INPUT)} bytes)"

    def uia() -> str:
        def run() -> str:
            from .controllers import DryRunController
            from .navigation.uia_windows import UIANavigator, foreground_window

            nav = UIANavigator(cfg.navigation, DryRunController(), dry_run=True)
            try:
                hwnd = foreground_window()
                if not hwnd:
                    return "UI Automation ready (no foreground window to scan)"
                t0 = time.monotonic()
                cands, _ = nav.find_candidates(hwnd)
                return f"UI Automation ready; scanned foreground window in {(time.monotonic() - t0) * 1000:.0f} ms ({len(cands)} candidates)"
            finally:
                nav.close()

        return _in_thread(run)

    def ocr() -> str:
        import cv2

        from .navigation.ocr_windows import WindowsOcr

        engine = WindowsOcr(cfg.navigation.ocr_language)
        img = np.full((120, 600, 3), 255, np.uint8)
        cv2.putText(img, "Next page", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4, cv2.LINE_AA)
        bgra = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        lines, _ = engine.recognize(bgra, 1.0)
        text = " ".join(w.text for line in lines for w in line)
        if "next" not in text.lower():
            raise AssertionError(f"OCR read {text!r} instead of 'Next page'")
        return f"Windows OCR ({engine.language}) read {text!r}"

    def capture() -> str:
        from .navigation.screen_windows import capture as grab, virtual_screen

        vs = virtual_screen()
        from .navigation.candidates import Rect

        img = grab(Rect(vs.left, vs.top, vs.left + 64, vs.top + 64))
        if img.shape[:2] != (64, 64):
            raise AssertionError(f"unexpected capture shape {img.shape}")
        return f"screen capture ok (virtual desktop {vs.width}x{vs.height})"

    def qt() -> str:
        from PySide6.QtWidgets import QApplication

        from .overlay.widgets import HudWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        hud = HudWindow(cfg.overlay)
        img = hud.grab().toImage()
        hud.close()
        app.processEvents()
        return f"Qt overlay renders ({img.width()}x{img.height()})"

    def camera() -> str:
        from .camera import Camera

        cam = Camera(cfg.camera).start()
        try:
            got = cam.read(0, timeout=3.0)
            if got is None:
                raise AssertionError("no frame within 3 s")
            h, w = got[2].shape[:2]
        finally:
            cam.stop()
        return f"camera {cfg.camera.index} delivers {w}x{h} frames"

    def hotkey() -> str:
        from .hotkeys import GlobalHotkey

        hk = GlobalHotkey(cfg.activation.pause_hotkey, lambda: None).start()
        try:
            if not hk.registered:
                raise AssertionError(f"{cfg.activation.pause_hotkey} is taken (Gesture Control already running?)")
        finally:
            hk.stop()
        return f"global hotkey {cfg.activation.pause_hotkey} available"

    checks = [
        Check("hand model", model),
        Check("input", input_controller),
        Check("ui automation", uia, required=cfg.navigation.mode == "uia"),
        Check("ocr", ocr, required=cfg.navigation.mode == "uia" and cfg.navigation.ocr_fallback),
        Check("screen capture", capture, required=cfg.navigation.ocr_fallback),
        Check("overlay (Qt)", qt, required=cfg.overlay.enabled),
        Check("camera", camera, required=False),
        Check("hotkey", hotkey, required=False),
    ]
    if sys.platform != "win32":
        checks = [c for c in checks if c.name in ("hand model", "overlay (Qt)", "camera")]
    return checks


def run_checks(checks: list[Check]) -> list[Result]:
    results = []
    for c in checks:
        t0 = time.monotonic()
        try:
            detail, ok = c.fn(), True
        except Exception as exc:  # noqa: BLE001 - every failure is reported
            detail, ok = f"{type(exc).__name__}: {exc}", False
            log.debug("self-test %s failed:\n%s", c.name, traceback.format_exc())
        results.append(Result(c.name, ok, c.required, detail, time.monotonic() - t0))
    return results


def report(results: list[Result]) -> tuple[str, int]:
    lines = []
    for r in results:
        tag = "PASS" if r.ok else ("FAIL" if r.required else "WARN")
        lines.append(f"{tag}  {r.name:<15} {r.detail}  ({r.seconds * 1000:.0f} ms)")
    failed = [r for r in results if not r.ok and r.required]
    lines.append("")
    lines.append("Self-test passed." if not failed else f"Self-test FAILED: {', '.join(r.name for r in failed)}")
    return "\n".join(lines), (1 if failed else 0)


def run(cfg: AppConfig, base_dir: Path) -> int:
    text, code = report(run_checks(build_checks(cfg, base_dir)))
    print(text, flush=True)
    for line in text.splitlines():
        if line:
            log.info("%s", line)
    return code
