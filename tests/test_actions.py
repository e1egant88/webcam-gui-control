import pytest

from gesture_control.actions import ActionDispatcher, SmoothScroller
from gesture_control.config import NavigationConfig, ScrollConfig
from gesture_control.controllers import DryRunController, parse_combo
from gesture_control.types import Gesture, GestureEvent


def event(g: Gesture, strength: float = 1.0) -> GestureEvent:
    return GestureEvent(g, 0.0, 0.0, 0.0, 0.2, 3.0 * strength, strength)


def scrolled(ctrl: DryRunController) -> list[int]:
    return [c[1] for c in ctrl.calls if c[0] == "scroll"]


def test_smooth_scroll_total_is_exact_and_eases_out():
    ctrl = DryRunController()
    s = SmoothScroller(ctrl, ScrollConfig(duration_s=0.25, high_resolution=True))
    s.submit(-360, now=0.0)
    t = 0.0
    while s.busy:
        t += 1 / 120
        s.step(t)
    steps = scrolled(ctrl)
    assert sum(steps) == -360
    assert len(steps) > 5
    assert all(v % 10 == 0 and v < 0 for v in steps)
    assert abs(steps[0]) >= abs(steps[-1])  # ease-out: big first, small last


def test_low_res_scroll_uses_whole_notches():
    ctrl = DryRunController()
    s = SmoothScroller(ctrl, ScrollConfig(duration_s=0.25, high_resolution=False))
    s.submit(360, now=0.0)
    t = 0.0
    while s.busy:
        t += 1 / 120
        s.step(t)
    steps = scrolled(ctrl)
    assert sum(steps) == 360
    assert all(v % 120 == 0 for v in steps)


def test_overlapping_scrolls_add_up():
    ctrl = DryRunController()
    s = SmoothScroller(ctrl, ScrollConfig(duration_s=0.25))
    s.submit(360, now=0.0)
    t = 0.0
    for _ in range(10):
        t += 1 / 120
        s.step(t)
    s.submit(360, now=t)
    while s.busy:
        t += 1 / 120
        s.step(t)
    assert sum(scrolled(ctrl)) == 720


def test_non_smooth_scroll_is_immediate():
    ctrl = DryRunController()
    s = SmoothScroller(ctrl, ScrollConfig(smooth=False))
    s.submit(-240)
    assert scrolled(ctrl) == [-240]


def test_cancel_stops_scroll():
    ctrl = DryRunController()
    s = SmoothScroller(ctrl, ScrollConfig(duration_s=0.25))
    s.submit(1200, now=0.0)
    s.step(0.02)
    s.cancel()
    assert not s.busy
    assert 0 < sum(scrolled(ctrl)) < 1200


def make_dispatcher(**nav):
    ctrl = DryRunController()
    scroll_cfg = ScrollConfig(smooth=False, notches_per_swipe=3, max_speed_multiplier=2.0)
    d = ActionDispatcher(ctrl, scroll_cfg, NavigationConfig(**nav), SmoothScroller(ctrl, scroll_cfg))
    return d, ctrl


def test_scroll_direction_and_speed_scaling():
    d, ctrl = make_dispatcher()
    d.handle(event(Gesture.SCROLL_UP))
    d.handle(event(Gesture.SCROLL_DOWN, strength=1.5))
    d.handle(event(Gesture.SCROLL_DOWN, strength=10))  # clamped to 2x
    assert scrolled(ctrl) == [360, -540, -720]


def test_navigation_keys():
    d, ctrl = make_dispatcher(next_keys=["alt+right"], previous_keys=["pageup"])
    d.handle(event(Gesture.NEXT))
    d.handle(event(Gesture.PREVIOUS))
    assert [c for c in ctrl.calls if c[0] == "keys"] == [
        ("keys", ("alt", "right")),
        ("keys", ("pageup",)),
    ]


def test_navigation_disabled():
    d, ctrl = make_dispatcher(mode="none")
    assert "disabled" in d.handle(event(Gesture.NEXT))
    assert ctrl.calls == []


def test_bad_key_config_fails_at_startup():
    with pytest.raises(ValueError):
        make_dispatcher(next_keys=["hyper+q"])


@pytest.mark.parametrize(
    "combo,expected",
    [
        ("Right", ["right"]),
        ("ctrl+alt+p", ["ctrl", "alt", "p"]),
        ("Control + PgDn", ["ctrl", "pagedown"]),
        ("f5", ["f5"]),
    ],
)
def test_parse_combo(combo, expected):
    assert parse_combo(combo) == expected


@pytest.mark.parametrize("combo", ["", "ctrl+", "ctrl+alt", "notakey"])
def test_parse_combo_rejects(combo):
    with pytest.raises(ValueError):
        parse_combo(combo)
