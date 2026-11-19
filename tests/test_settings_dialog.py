import copy
import tomllib

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gesture_control.config import AppConfig  # noqa: E402
from gesture_control.settings_schema import all_specs  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make(qapp, tmp_path, live=None, saved=None):
    from gesture_control.overlay.settings_dialog import SettingsDialog

    live = live or AppConfig()
    base = AppConfig()
    saved = saved or AppConfig()
    applied = []
    d = SettingsDialog(live, base, saved, tmp_path / "settings.toml", on_live_applied=lambda: applied.append(1))
    return d, live, applied


def ed(d, section, key):
    return d.editors[(section, key)]


def test_every_spec_has_an_editor(qapp, tmp_path):
    d, _, _ = make(qapp, tmp_path)
    assert len(d.editors) == len(all_specs())


def test_untouched_apply_changes_nothing(qapp, tmp_path):
    d, live, applied = make(qapp, tmp_path)
    before = copy.deepcopy(live)
    assert d.apply()
    assert live == before and applied == [] and not d.restart_pending
    assert not (tmp_path / "settings.toml").exists()


def test_live_and_restart_fields(qapp, tmp_path):
    d, live, applied = make(qapp, tmp_path)
    ed(d, "gestures", "min_speed").setValue(5.5)
    ed(d, "overlay", "corner").setCurrentText("top-left")
    ed(d, "navigation", "mode").setCurrentText("keys")
    ed(d, "navigation", "next_keys").setText("alt+right, pagedown")
    assert d.apply()
    # Live fields are applied to the running config...
    assert live.gestures.min_speed == 5.5 and live.overlay.corner == "top-left"
    # ...restart-only fields are saved but not applied.
    assert live.navigation.mode == "uia" and live.navigation.next_keys == ["right"]
    assert d.restart_pending and d.restart_row.isVisibleTo(d)
    assert applied == [1]
    saved = tomllib.loads((tmp_path / "settings.toml").read_text(encoding="utf-8"))
    assert saved == {
        "gestures": {"min_speed": 5.5},
        "overlay": {"corner": "top-left"},
        "navigation": {"mode": "keys", "next_keys": ["alt+right", "pagedown"]},
    }


def test_invalid_input_is_rejected(qapp, tmp_path):
    d, live, _ = make(qapp, tmp_path)
    ed(d, "gestures", "min_speed").setValue(6.0)
    ed(d, "navigation", "next_keys").setText("hyper+x")
    assert not d.apply()
    assert "next_keys" in d.error.text() and d.error.isVisibleTo(d)
    assert live.gestures.min_speed == AppConfig().gestures.min_speed  # nothing applied
    assert not (tmp_path / "settings.toml").exists()


def test_command_line_overrides_are_not_saved(qapp, tmp_path):
    live = AppConfig()
    live.dry_run = True  # e.g. started with --dry-run
    d, live, _ = make(qapp, tmp_path, live=live)
    assert not ed(d, "", "dry_run").isChecked()  # dialog shows the saved value
    ed(d, "gestures", "min_speed").setValue(4.0)
    assert d.apply()
    assert live.dry_run is True  # untouched for this run
    assert "dry_run" not in tomllib.loads((tmp_path / "settings.toml").read_text(encoding="utf-8"))


def test_restore_defaults_clears_file(qapp, tmp_path):
    saved = AppConfig()
    saved.gestures.min_speed = 8.0
    d, live, _ = make(qapp, tmp_path, saved=saved)
    (tmp_path / "settings.toml").write_text("[gestures]\nmin_speed = 8.0\n")
    assert ed(d, "gestures", "min_speed").value() == 8.0
    d.restore_defaults()
    assert d.apply()
    assert not (tmp_path / "settings.toml").exists()
    assert live.gestures.min_speed == AppConfig().gestures.min_speed


def test_precise_value_not_rounded_away(qapp, tmp_path):
    saved = AppConfig()
    saved.gestures.window_s = 0.333  # spin box shows 2 decimals
    d, live, _ = make(qapp, tmp_path, saved=saved)
    assert d.apply()
    # Untouched: kept as 0.333 (differs from the 0.35 default, so it is saved),
    # not silently rounded to the 0.33 the box displays, and not re-applied.
    data = tomllib.loads((tmp_path / "settings.toml").read_text(encoding="utf-8"))
    assert data["gestures"]["window_s"] == 0.333
    assert live.gestures.window_s == AppConfig().gestures.window_s
