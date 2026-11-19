"""Engine wiring: observations in, actions and UI events out (no camera, no UI)."""

from gesture_control.activation import ActivationState
from gesture_control.config import AppConfig
from gesture_control.controllers import DryRunController
from gesture_control.engine import Engine
from gesture_control.types import Gesture

from helpers import Script


def make_engine(**nav):
    cfg = AppConfig()
    cfg.navigation.mode = nav.get("mode", "keys")
    cfg.scroll.smooth = False  # scroll immediately, no animation thread
    ctrl = DryRunController()
    return Engine(cfg, ctrl), ctrl


def feed(engine, frames):
    snaps = [engine.process(None, f, f.timestamp if f else 0.0) for f in frames if f is not None]
    return snaps


def test_arm_then_scroll_and_events():
    engine, ctrl = make_engine()
    s = Script(y=0.3).hold(1.0)  # dwell to arm
    snaps = feed(engine, s)
    assert snaps[-1].state is ActivationState.ACTIVE
    s2 = Script(y=0.3, t=s.t).hold(0.1).move(0, 2.0, 0.2).hold(0.3)
    feed(engine, s2)
    scrolls = [c[1] for c in ctrl.calls if c[0] == "scroll"]
    # 3 notches (360) down, scaled up to 2.5x for a fast swipe.
    assert len(scrolls) == 1 and -900 <= scrolls[0] <= -360
    events = engine.drain_events()
    assert [e.gesture for e in events] == [Gesture.SCROLL_DOWN] and events[0].acted
    assert engine.drain_events() == []


def test_swipe_while_idle_is_ignored():
    engine, ctrl = make_engine()
    # Fast swipe without dwelling first: detector fires, but nothing executes.
    # The initial hold is too short to arm: 0.3 s < arm_hold_s (0.6 s).
    s = Script().hold(0.3).move(2.5, 0, 0.2).hold(0.2)
    snaps = feed(engine, s)
    assert all(sn.state is not ActivationState.ACTIVE for sn in snaps)
    assert ctrl.calls == []
    assert engine.drain_events() == []
    assert "ignored" in snaps[-1].last_action


def test_next_sends_keys_in_keys_mode():
    engine, ctrl = make_engine()
    s = Script(x=0.3).hold(1.0).move(2.5, 0, 0.2).hold(0.3)
    feed(engine, s)
    assert ("keys", ("right",)) in ctrl.calls


def test_pause_blocks_everything():
    engine, ctrl = make_engine()
    engine.toggle_pause()
    s = Script(y=0.3).hold(1.0).move(0, 2.0, 0.2).hold(0.3)
    snaps = feed(engine, s)
    assert snaps[-1].state is ActivationState.PAUSED
    assert ctrl.calls == []
    assert engine.paused


def test_snapshot_fields():
    engine, _ = make_engine()
    (snap,) = feed(engine, Script().hold(1 / 30))
    assert snap.controller_name == "dry-run"
    assert snap.state is ActivationState.ARMING
    assert snap.obs is not None
