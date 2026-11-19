from gesture_control.activation import ActivationController, ActivationState as S
from gesture_control.config import ActivationConfig
from gesture_control.types import Pose

from helpers import DT, obs


def feed(ctrl, frames, speed=0.0):
    state = None
    for f in frames:
        t = f[0]
        o = None if f[1] is None else obs(t, 0.5, 0.5, f[1])
        state = ctrl.update(o, speed, t)
    return state


def frames(t0, seconds, pose):
    n = int(round(seconds / DT))
    return [(t0 + i * DT, pose) for i in range(n)]


def test_dwell_arms_after_hold():
    c = ActivationController(ActivationConfig(arm_hold_s=0.6))
    assert feed(c, frames(0, 0.3, Pose.OPEN_PALM)) is S.ARMING
    assert 0.3 < c.arming_progress < 0.7
    assert feed(c, frames(0.3, 0.4, Pose.OPEN_PALM)) is S.ACTIVE


def test_moving_hand_does_not_arm():
    c = ActivationController(ActivationConfig())
    assert feed(c, frames(0, 2.0, Pose.OPEN_PALM), speed=5.0) is S.IDLE


def test_fist_does_not_arm():
    c = ActivationController(ActivationConfig())
    assert feed(c, frames(0, 2.0, Pose.FIST)) is S.IDLE


def test_disarm_when_hand_lost():
    c = ActivationController(ActivationConfig(disarm_after_lost_s=1.0))
    assert feed(c, frames(0, 1.0, Pose.OPEN_PALM)) is S.ACTIVE
    assert feed(c, frames(1.0, 0.5, None)) is S.ACTIVE  # brief dropout tolerated
    assert feed(c, frames(1.5, 0.6, None)) is S.IDLE


def test_fist_hold_disarms():
    c = ActivationController(ActivationConfig(fist_hold_s=0.4))
    feed(c, frames(0, 1.0, Pose.OPEN_PALM))
    assert feed(c, frames(1.0, 0.2, Pose.FIST)) is S.ACTIVE  # brief fist tolerated
    assert feed(c, frames(1.2, 0.3, Pose.FIST)) is S.IDLE


def test_pause_overrides_and_disarms():
    c = ActivationController(ActivationConfig())
    feed(c, frames(0, 1.0, Pose.OPEN_PALM))
    c.toggle_pause()
    assert feed(c, frames(1.0, 1.0, Pose.OPEN_PALM)) is S.PAUSED
    c.toggle_pause()
    # Must re-arm after un-pausing.
    assert feed(c, frames(2.0, 0.1, Pose.OPEN_PALM)) is S.ARMING


def test_always_mode():
    c = ActivationController(ActivationConfig(mode="always"))
    assert feed(c, frames(0, 0.1, None)) is S.ACTIVE
    c.set_paused(True)
    assert feed(c, frames(0.1, 0.1, None)) is S.PAUSED


def test_start_paused():
    c = ActivationController(ActivationConfig(start_paused=True))
    assert c.state is S.PAUSED
