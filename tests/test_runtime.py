import logging
import sys
import uuid
from pathlib import Path

import pytest

from gesture_control import runtime
from gesture_control.selftest import Check, report, run_checks


def test_single_instance_blocks_second_copy():
    if sys.platform != "win32":
        pytest.skip("named mutex is Windows-only")
    name = f"Local\\GestureControlTest-{uuid.uuid4()}"
    first, second = runtime.SingleInstance(name), runtime.SingleInstance(name)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()  # free again after release
    second.release()


def test_default_paths_from_source(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert not runtime.is_frozen()
    assert runtime.default_config_path() == tmp_path / "config.toml"


def test_default_paths_when_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "GestureControl" / "GestureControl.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert runtime.is_frozen()
    assert runtime.default_config_path() == exe.parent.resolve() / "config.toml"


def test_ensure_std_streams(monkeypatch):
    monkeypatch.setattr(sys, "stderr", None)
    runtime.ensure_std_streams()
    sys.stderr.write("ignored")  # must not raise


def test_log_file_written(tmp_path):
    root = logging.getLogger()
    saved = list(root.handlers), root.level
    try:
        log_file = tmp_path / "logs" / "gc.log"
        runtime.setup_logging(False, log_file)
        logging.getLogger("gesture_control.test").info("hello file")
        for h in root.handlers:
            h.flush()
        assert "hello file" in log_file.read_text(encoding="utf-8")
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)
            h.close()
        for h in saved[0]:
            root.addHandler(h)
        root.setLevel(saved[1])


def test_log_file_path_is_per_user():
    p = runtime.log_file_path()
    assert p.name == "gesture-control.log" and "GestureControl" in str(p)


def test_self_test_report():
    def boom():
        raise RuntimeError("no camera")

    results = run_checks([
        Check("a", lambda: "fine"),
        Check("camera", boom, required=False),
    ])
    text, code = report(results)
    assert code == 0
    assert "PASS  a" in text and "WARN  camera" in text and "no camera" in text
    assert "Self-test passed." in text

    text, code = report(run_checks([Check("model", boom)]))
    assert code == 1 and "FAIL  model" in text and "FAILED: model" in text


def test_self_test_cli_flag_parses():
    from gesture_control.__main__ import build_parser

    args = build_parser().parse_args(["--self-test", "--log-file"])
    assert args.self_test and args.log_file == "default"
    assert build_parser().parse_args([]).config is None
