from gesture_control.navigation.candidates import Rect
from gesture_control.overlay.geometry import Monitor, match_monitors, monitor_for, phys_to_logical

# Left: 4K at 150% (physical 3840x2160, logical 2560x1440).
# Right: 1080p at 100%, physically to the right of the 4K screen.
LEFT = Monitor("\\\\.\\DISPLAY1", Rect(0, 0, 3840, 2160), (0, 0, 2560, 1440), 1.5)
RIGHT = Monitor("\\\\.\\DISPLAY2", Rect(3840, 0, 5760, 1080), (2560, 0, 1920, 1080), 1.0)
MONS = [LEFT, RIGHT]


def test_scaled_monitor():
    assert phys_to_logical(Rect(300, 600, 450, 660), MONS) == (200.0, 400.0, 100.0, 40.0)


def test_unscaled_second_monitor():
    assert phys_to_logical(Rect(4000, 100, 4100, 140), MONS) == (2720.0, 100.0, 100.0, 40.0)


def test_rect_spanning_monitors_uses_centre():
    assert monitor_for(Rect(3800, 10, 3900, 50), MONS) is RIGHT  # centre x=3850
    assert monitor_for(Rect(3700, 10, 3900, 50), MONS) is LEFT  # centre x=3800


def test_off_screen_uses_nearest():
    assert monitor_for(Rect(6000, 10, 6100, 50), MONS) is RIGHT


def test_no_monitors():
    assert phys_to_logical(Rect(0, 0, 10, 10), []) is None


def test_match_by_name():
    phys = [("\\\\.\\DISPLAY2", RIGHT.physical), ("\\\\.\\DISPLAY1", LEFT.physical)]
    log = [(LEFT.name, LEFT.logical, 1.5), (RIGHT.name, RIGHT.logical, 1.0)]
    assert match_monitors(phys, log) == MONS


def test_match_falls_back_to_order():
    phys = [("A", RIGHT.physical), ("B", LEFT.physical)]
    log = [("Dell", LEFT.logical, 1.5), ("LG", RIGHT.logical, 1.0)]
    out = match_monitors(phys, log)
    assert [m.physical for m in out] == [LEFT.physical, RIGHT.physical]
    assert [m.dpr for m in out] == [1.5, 1.0]
