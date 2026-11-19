import pytest

from gesture_control import __main__ as entry


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    # Don't take the real single-instance lock (the app may be running) and
    # don't replace pytest's logging handlers.
    monkeypatch.setattr(entry.SingleInstance, "acquire", lambda self: True)
    monkeypatch.setattr(entry, "setup_logging", lambda verbose, log_file: None)


def test_already_running(monkeypatch):
    monkeypatch.setattr(entry.SingleInstance, "acquire", lambda self: False)
    monkeypatch.setattr(entry, "run_once", lambda args: pytest.fail("must not run"))
    assert entry.main([]) == entry.ALREADY_RUNNING_EXIT_CODE


def test_restart_loop(monkeypatch):
    codes = iter([entry.RESTART_EXIT_CODE, entry.RESTART_EXIT_CODE, 0])
    calls = []

    def fake_run_once(args):
        calls.append(args.config)
        return next(codes)

    monkeypatch.setattr(entry, "run_once", fake_run_once)
    assert entry.main(["-c", "x.toml"]) == 0
    assert calls == ["x.toml"] * 3


def test_error_code_passes_through(monkeypatch):
    monkeypatch.setattr(entry, "run_once", lambda args: 2)
    assert entry.main([]) == 2


def test_overlay_and_main_agree_on_restart_code():
    import pytest

    pytest.importorskip("PySide6")
    from gesture_control.overlay.qt_app import RESTART_EXIT_CODE

    assert RESTART_EXIT_CODE == entry.RESTART_EXIT_CODE
