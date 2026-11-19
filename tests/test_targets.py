import sys
import time

import pytest

from gesture_control.targets import WindowTarget


def wt(**kw):
    base = dict(app="chrome.exe", title="t", class_name="Chrome_WidgetWin_1", elevated=False, desktop=False)
    base.update(kw)
    return WindowTarget(**base)


def test_describe():
    assert wt().describe() == "chrome.exe"
    assert not wt().problem
    assert "administrator" in wt(app="taskmgr.exe", elevated=True).describe()
    assert "nothing to scroll" in wt(app="explorer.exe", class_name="Progman", desktop=True).describe()
    assert wt(elevated=True).problem and wt(desktop=True).problem
    assert wt(app="", class_name="SomeClass").describe() == "SomeClass"


def test_engine_names_scroll_target(monkeypatch):
    from gesture_control import targets
    from gesture_control.config import AppConfig
    from gesture_control.controllers import DryRunController
    from gesture_control.engine import Engine

    from helpers import Script

    monkeypatch.setattr(targets, "pointer_target", lambda: wt(app="taskmgr.exe", elevated=True))
    cfg = AppConfig()
    cfg.navigation.mode = "keys"
    cfg.scroll.smooth = False
    engine = Engine(cfg, DryRunController())
    snaps = [engine.process(None, f, f.timestamp) for f in Script(y=0.3).hold(1.0).move(0, 2.0, 0.2).hold(0.3)]
    assert "taskmgr.exe" in snaps[-1].last_action and "administrator" in snaps[-1].last_action


def test_target_failure_never_breaks_scrolling(monkeypatch):
    from gesture_control import targets
    from gesture_control.config import AppConfig
    from gesture_control.controllers import DryRunController
    from gesture_control.engine import Engine

    from helpers import Script

    def boom():
        raise OSError("nope")

    monkeypatch.setattr(targets, "pointer_target", boom)
    cfg = AppConfig()
    cfg.navigation.mode = "keys"
    cfg.scroll.smooth = False
    ctrl = DryRunController()
    engine = Engine(cfg, ctrl)
    for f in Script(y=0.3).hold(1.0).move(0, 2.0, 0.2).hold(0.3):
        engine.process(None, f, f.timestamp)
    assert [c for c in ctrl.calls if c[0] == "scroll"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_window_target_real_windows():
    import ctypes
    import os

    from gesture_control.targets import pointer_target, window_target

    from win32_window import Win32TestWindow

    with Win32TestWindow([], x=150, y=150) as w:
        time.sleep(0.1)
        t = window_target(w.hwnd)
        assert t.app.lower() == os.path.basename(sys.executable).lower()
        assert not t.elevated and not t.desktop
    tray = ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None)
    if tray:
        assert window_target(tray).desktop
    assert pointer_target() is not None  # whatever is under the cursor now
