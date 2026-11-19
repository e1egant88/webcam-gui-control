import math
from pathlib import Path

import pytest

from gesture_control.config import load_config
from gesture_control.hand_geometry import observation_from_landmarks
from gesture_control.hotkeys import MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, parse_hotkey
from gesture_control.types import Pose

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_config_loads():
    cfg = load_config(ROOT / "config.toml")
    assert cfg.camera.mirror is True
    assert cfg.activation.mode == "dwell"


def test_missing_config_uses_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.gestures.window_s > 0


def test_config_overrides_and_int_to_float(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text("[gestures]\nmin_speed = 4\n[camera]\nindex = 2\n")
    cfg = load_config(p)
    assert cfg.gestures.min_speed == 4.0 and isinstance(cfg.gestures.min_speed, float)
    assert cfg.camera.index == 2


@pytest.mark.parametrize(
    "text",
    [
        "[camera]\nmirror = 1\n",
        "[gestures]\nsmoothing_alpha = 0\n",
        "[activation]\nmode = 'sometimes'\n",
        "[camera]\nindex = 'zero'\n",
    ],
)
def test_invalid_config_rejected(tmp_path, text):
    p = tmp_path / "c.toml"
    p.write_text(text)
    with pytest.raises(ValueError):
        load_config(p)


def test_hotkey_parse():
    mods, key = parse_hotkey("ctrl+alt+p")
    assert mods == MOD_CONTROL | MOD_ALT | MOD_NOREPEAT and key == "p"
    with pytest.raises(ValueError):
        parse_hotkey("p")


def _hand(extended: bool, curled_fingers: int = 0):
    """Upright synthetic hand: wrist at bottom, fingers pointing up."""
    pts = [(0.5, 0.0)] * 21
    pts[0] = (0.5, 0.8)
    mcp_x = {5: 0.44, 9: 0.49, 13: 0.54, 17: 0.59}
    for mcp, x in mcp_x.items():
        pts[mcp] = (x, 0.6)
    for i, (mcp, x) in enumerate(mcp_x.items()):
        pip, dip, tip = mcp + 1, mcp + 2, mcp + 3
        curled = (not extended) or i < curled_fingers
        pts[pip] = (x, 0.5)
        pts[dip] = (x, 0.55 if curled else 0.42)
        pts[tip] = (x, 0.62 if curled else 0.35)
    for i in range(1, 5):  # thumb, irrelevant
        pts[i] = (0.4, 0.7)
    return pts


def test_open_palm_and_fist_classification():
    open_obs = observation_from_landmarks(_hand(True), 0.0, aspect=4 / 3)
    fist_obs = observation_from_landmarks(_hand(False), 0.0, aspect=4 / 3)
    other_obs = observation_from_landmarks(_hand(True, curled_fingers=2), 0.0, aspect=4 / 3)
    assert open_obs.pose is Pose.OPEN_PALM and open_obs.extended_fingers == 4
    assert fist_obs.pose is Pose.FIST and fist_obs.extended_fingers == 0
    assert other_obs.pose is Pose.OTHER


def test_palm_size_and_aspect():
    o = observation_from_landmarks(_hand(True), 0.0, aspect=4 / 3)
    # wrist (0.5, 0.8) -> middle MCP (0.49, 0.6), x scaled by 4/3
    assert math.isclose(o.palm_size, math.hypot(0.01 * 4 / 3, 0.2))
    assert math.isclose(o.palm_y, (0.8 + 0.6 * 4) / 5)
