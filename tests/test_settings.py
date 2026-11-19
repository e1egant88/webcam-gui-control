import logging
import tomllib
from pathlib import Path

import pytest

from gesture_control import settings_store
from gesture_control.actions import SmoothScroller
from gesture_control.config import AppConfig, apply_overrides, load_base_config, load_config
from gesture_control.controllers import DryRunController
from gesture_control.engine import Engine
from gesture_control.settings_schema import check_schema

ROOT = Path(__file__).resolve().parents[1]


def test_dumps_round_trip():
    data = {
        "dry_run": True,
        "gestures": {"min_speed": 4.5, "invert_vertical": True, "min_samples": 5},
        "navigation": {
            "next_keys": ["alt+right", "pagedown"],
            "extra_next_names": ["weiter", "suivant", "次へ"],
            "ocr_language": 'odd "quoted" \\ value\twith tab',
        },
        "overlay": {},
    }
    loaded = tomllib.loads(settings_store.dumps(data))
    expected = {k: v for k, v in data.items() if v != {}}
    assert loaded == expected


def test_dumps_rejects_bad_values():
    with pytest.raises(ValueError):
        settings_store.dumps({"x": float("nan")})
    with pytest.raises(TypeError):
        settings_store.dumps({"x": object()})


def test_diff_only_changed():
    base = AppConfig()
    cfg = AppConfig()
    cfg.gestures.min_speed = 5.0
    cfg.navigation.next_keys = ["alt+right"]
    cfg.dry_run = True
    assert settings_store.diff(cfg, base) == {
        "gestures": {"min_speed": 5.0},
        "navigation": {"next_keys": ["alt+right"]},
        "dry_run": True,
    }
    assert settings_store.diff(base, AppConfig()) == {}


def test_save_writes_diff_and_removes_when_empty(tmp_path):
    p = tmp_path / "sub" / "settings.toml"
    base = AppConfig()
    cfg = AppConfig()
    cfg.overlay.corner = "top-left"
    settings_store.save(cfg, base, p)
    assert tomllib.loads(p.read_text(encoding="utf-8")) == {"overlay": {"corner": "top-left"}}
    settings_store.save(AppConfig(), base, p)
    assert not p.exists()


def test_layering(tmp_path):
    proj = tmp_path / "config.toml"
    proj.write_text("[gestures]\nmin_speed = 4.0\nwindow_s = 0.5\n")
    user = tmp_path / "settings.toml"
    user.write_text("[gestures]\nmin_speed = 6.0\n")
    cfg = load_config(proj, user)
    assert cfg.gestures.min_speed == 6.0  # user wins
    assert cfg.gestures.window_s == 0.5  # project value kept
    assert load_base_config(proj).gestures.min_speed == 4.0


@pytest.mark.parametrize(
    "text",
    ["[gestures]\nmin_speed = -1\n", "not toml at all [[[", "[navigation]\nnext_keys = ['hyper+x']\n"],
)
def test_bad_user_settings_ignored(tmp_path, caplog, text):
    user = tmp_path / "settings.toml"
    user.write_text(text)
    with caplog.at_level(logging.WARNING):
        cfg = load_config(None, user)
    assert cfg.gestures.min_speed == AppConfig().gestures.min_speed
    assert "Ignoring user settings" in caplog.text


def test_validate_checks_keys_and_hotkey():
    with pytest.raises(ValueError, match="next_keys"):
        apply_overrides(AppConfig(), {"navigation": {"next_keys": ["ctrl+"]}})
    with pytest.raises(ValueError, match="pause_hotkey"):
        apply_overrides(AppConfig(), {"activation": {"pause_hotkey": "p"}})


def test_schema_matches_config():
    assert check_schema(AppConfig()) == []
    assert check_schema(load_base_config(ROOT / "config.toml")) == []


def test_copy_into_keeps_section_identity():
    live = AppConfig()
    gestures = live.gestures
    new = apply_overrides(live, {"gestures": {"min_speed": 7.0}, "dry_run": True})
    settings_store.copy_into(live, new)
    assert live.gestures is gestures and gestures.min_speed == 7.0 and live.dry_run


def test_live_changes_reach_running_components():
    cfg = AppConfig()
    cfg.navigation.mode = "keys"
    engine = Engine(cfg, DryRunController())
    cfg.gestures.min_speed = 9.0
    assert engine.detector.cfg.min_speed == 9.0
    scroller = SmoothScroller(DryRunController(), cfg.scroll)
    assert scroller.granularity == 10
    cfg.scroll.high_resolution = False
    assert scroller.granularity == 120


def test_user_settings_path_is_per_user():
    p = settings_store.user_settings_path()
    assert p.name == "settings.toml" and "GestureControl" in str(p)
