import random

import pytest

from gesture_control.config import GestureConfig
from gesture_control.gestures import GestureDetector
from gesture_control.types import Gesture, Pose

from helpers import Script, run


def detector(**overrides) -> GestureDetector:
    return GestureDetector(GestureConfig(**overrides))


def gestures(events):
    return [e.gesture for e in events]


@pytest.mark.parametrize(
    "dx,dy,expected",
    [
        (2.5, 0, Gesture.NEXT),
        (-2.5, 0, Gesture.PREVIOUS),
        (0, 2.0, Gesture.SCROLL_DOWN),
        (0, -2.0, Gesture.SCROLL_UP),
    ],
)
def test_basic_swipes(dx, dy, expected):
    s = Script().hold(0.5).move(dx, dy, 0.2).hold(0.3)
    assert gestures(run(detector(), s)) == [expected]


def test_event_reports_metrics():
    (ev,) = run(detector(), Script().hold(0.5).move(0, 2.0, 0.2).hold(0.3))
    assert ev.dy > 1.0
    assert abs(ev.dx) < 0.1
    assert ev.speed >= 3.0
    assert ev.strength >= 1.0


@pytest.mark.parametrize("invert_h,invert_v", [(True, False), (False, True)])
def test_inversion(invert_h, invert_v):
    d = detector(invert_horizontal=invert_h, invert_vertical=invert_v)
    s = Script().hold(0.5).move(2.5, 0, 0.2).hold(1.0).move(0, 2.0, 0.2).hold(0.3)
    exp_h = Gesture.PREVIOUS if invert_h else Gesture.NEXT
    exp_v = Gesture.SCROLL_UP if invert_v else Gesture.SCROLL_DOWN
    assert gestures(run(d, s)) == [exp_h, exp_v]


def test_slow_drift_does_not_fire():
    # 3 palm sizes over 2 seconds = 1.5 palms/s, well below min_speed.
    s = Script().hold(0.5).move(3.0, 0, 2.0).move(0, 3.0, 2.0)
    assert run(detector(), s) == []


def test_short_twitch_does_not_fire():
    s = Script().hold(0.5).move(0, 0.6, 0.08).hold(0.5)
    assert run(detector(), s) == []


def test_diagonal_does_not_fire():
    s = Script().hold(0.5).move(2.0, 2.0, 0.2).hold(0.3)
    assert run(detector(), s) == []


def test_fist_movement_is_ignored():
    s = Script().hold(0.5, Pose.FIST).move(3.0, 0, 0.2, Pose.FIST).move(0, 3.0, 0.2, Pose.FIST)
    assert run(detector(), s) == []


def test_other_pose_movement_is_ignored():
    s = Script().hold(0.5, Pose.OTHER).move(0, 3.0, 0.2, Pose.OTHER)
    assert run(detector(), s) == []


def test_hand_entering_frame_does_not_fire():
    # The hand appears and immediately moves fast (e.g. raising it into view).
    s = Script(y=0.9).move(0, -3.0, 0.2).hold(0.3)
    assert run(detector(), s) == []


def test_opening_hand_mid_motion_does_not_fire():
    s = Script().hold(0.5, Pose.FIST).move(0, -0.5, 0.05, Pose.FIST).move(0, -3.0, 0.2).hold(0.3)
    assert run(detector(), s) == []


def test_return_stroke_is_suppressed():
    # Swipe right, then bring the hand straight back: only NEXT fires.
    s = Script().hold(0.5).move(2.5, 0, 0.2).move(-2.5, 0, 0.25).hold(0.5)
    assert gestures(run(detector(), s)) == [Gesture.NEXT]


def test_vertical_return_stroke_is_suppressed():
    s = Script().hold(0.5).move(0, 2.0, 0.18).move(0, -2.0, 0.2).hold(0.5)
    assert gestures(run(detector(), s)) == [Gesture.SCROLL_DOWN]


def test_intentional_opposite_after_pause_fires():
    s = Script().hold(0.5).move(2.5, 0, 0.2).hold(1.0).move(-2.5, 0, 0.2).hold(0.3)
    assert gestures(run(detector(), s)) == [Gesture.NEXT, Gesture.PREVIOUS]


def test_one_long_stroke_fires_once():
    # A long continuous fast stroke must not repeat after the cooldown.
    s = Script(y=0.1).hold(0.5).move(0, 6.0, 0.6).hold(0.3)
    assert gestures(run(detector(), s)) == [Gesture.SCROLL_DOWN]


def test_paddling_scrolls_repeatedly_in_one_direction():
    # Down strokes with quick returns: every down stroke scrolls, returns don't.
    s = Script(y=0.3).hold(0.5)
    for _ in range(4):
        s.move(0, 1.8, 0.18).move(0, -1.8, 0.25)
    s.hold(0.3)
    assert gestures(run(detector(), s)) == [Gesture.SCROLL_DOWN] * 4


def test_horizontal_cooldown_blocks_double_next():
    # Two right swipes back-to-back faster than the horizontal cooldown.
    s = Script(x=0.2).hold(0.5).move(2.0, 0, 0.15).hold(0.05).move(2.0, 0, 0.15).hold(0.3)
    assert gestures(run(detector(), s)) == [Gesture.NEXT]


def test_lost_hand_clears_history():
    # Hand vanishes mid-move and reappears further along: no jump-based swipe.
    s = Script().hold(0.5).move(0, 0.5, 0.05).gone(0.2)
    s.y += 2.0 * 0.15
    s.move(0, 0.3, 0.05).hold(0.3)
    assert run(detector(), s) == []


def test_jitter_does_not_fire():
    rng = random.Random(42)
    s = Script().hold(0.3)
    frames = list(s)
    t = s.t
    from helpers import DT, obs

    for i in range(300):  # 10 s of noisy hovering (+-0.25 palm)
        t += DT
        frames.append(obs(t, 0.65 + rng.uniform(-0.04, 0.04), 0.5 + rng.uniform(-0.04, 0.04)))
    assert run(detector(), frames) == []


def test_distance_invariance():
    # Same motion in palm units, but the hand is twice as close (twice as big).
    from helpers import DT, obs

    frames = []
    t = 0.0
    big = 0.30
    x = 0.6
    for _ in range(15):
        t += DT
        frames.append(obs(t, x, 0.4, size=big))
    for i in range(1, 7):
        t += DT
        frames.append(obs(t, x, 0.4 + 2.0 * big * i / 6, size=big))
    assert gestures(run(detector(), frames)) == [Gesture.SCROLL_DOWN]


def test_duplicate_timestamps_ignored():
    d = detector()
    s = Script().hold(0.5)
    run(d, s)
    last = s.frames[-1]
    assert d.update(last) is None  # same timestamp again
