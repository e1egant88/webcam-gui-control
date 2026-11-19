import pytest

from gesture_control.navigation.candidates import ControlKind, Rect, UICandidate
from gesture_control.navigation.scoring import (
    ScoringOptions,
    choose_target,
    is_blocked,
    match_identifier,
    match_name,
)
from gesture_control.types import Gesture

NEXT, PREV = Gesture.NEXT, Gesture.PREVIOUS
WINDOW = Rect(0, 0, 1920, 1080)


def cand(name="", x=900, y=900, kind=ControlKind.LINK, **kw) -> UICandidate:
    return UICandidate(name=name, kind=kind, rect=Rect(x - 40, y - 15, x + 40, y + 15), **kw)


# ---------------------------------------------------------------- match_name
@pytest.mark.parametrize(
    "name,direction,score",
    [
        ("Next", NEXT, 100),
        ("NEXT", NEXT, 100),
        ("next.", NEXT, 100),
        ("Next ›", NEXT, 100),
        ("Next »", NEXT, 100),
        ("Next >", NEXT, 100),
        ("Next page", NEXT, 90),
        ("Next slide", NEXT, 90),
        ("Next chapter", NEXT, 90),
        ("Go to next page", NEXT, 85),
        ("Show the next image", NEXT, 85),
        ("›", NEXT, 70),
        ("»", NEXT, 70),
        ("→", NEXT, 70),
        ("Previous", PREV, 100),
        ("Prev", PREV, 100),
        ("« Previous", PREV, 100),
        ("< Prev page", PREV, 90),
        ("‹", PREV, 70),
        ("Go to previous page", PREV, 85),
    ],
)
def test_match_name_accepts(name, direction, score):
    m = match_name(name, direction)
    assert m is not None and m.score == score


@pytest.mark.parametrize(
    "name,direction",
    [
        ("Next steps for your career", NEXT),
        ("Previous orders", PREV),
        ("Nextcloud", NEXT),
        ("Preview", PREV),
        ("Next", PREV),
        ("Previous", NEXT),
        ("‹", NEXT),
        ("‹ Prev | Next ›", NEXT),
        ("< Back", NEXT),
        ("Back", PREV),        # back/forward off by default
        ("Forward", NEXT),
        ("", NEXT),
        ("Home > Products > Shoes", NEXT),
    ],
)
def test_match_name_rejects(name, direction):
    assert match_name(name, direction) is None


def test_back_forward_optional():
    assert match_name("Back", PREV, include_back_forward=True).score == 65
    assert match_name("Forward", NEXT, include_back_forward=True).score == 65


def test_extra_names():
    assert match_name("Weiter", NEXT, extra_names=["weiter"]).score == 95


@pytest.mark.parametrize(
    "aid,direction,ok",
    [
        ("nextButton", NEXT, True),
        ("pnnext", NEXT, True),
        ("btn-prev", PREV, True),
        ("carousel_prev_arrow", PREV, True),
        ("previewPane", PREV, False),
        ("contextMenu", NEXT, False),
        ("nav-prev-next", NEXT, False),  # both directions -> unclear
    ],
)
def test_match_identifier(aid, direction, ok):
    assert (match_identifier(aid, "", direction) is not None) is ok


def test_blocked_words():
    assert is_blocked("Next: Pay now", ["pay"])
    assert is_blocked("Sign out", ["sign out"])
    assert not is_blocked("Next page", ["pay"])
    assert not is_blocked("Payload viewer next", ["pay"])  # whole words only


# ------------------------------------------------------------ choose_target
def test_picks_obvious_next():
    sel = choose_target([cand("Next"), cand("Previous", x=700)], NEXT, WINDOW)
    assert sel.target is not None and sel.target.candidate.name == "Next"


def test_pair_bonus_applied():
    sel = choose_target([cand("Next"), cand("Previous", x=700)], NEXT, WINDOW)
    assert any("paired" in r for r in sel.target.reasons)


def test_nothing_matching():
    sel = choose_target([cand("Home"), cand("Next steps for you")], NEXT, WINDOW)
    assert sel.target is None and sel.reason == "no matching control"


@pytest.mark.parametrize(
    "c,reason",
    [
        (cand("Next", enabled=False), "disabled"),
        (cand("Next", offscreen=True), "off-screen"),
        (cand("Next", x=3000), "outside window"),
        (UICandidate("Next", ControlKind.BUTTON, Rect(5, 5, 5, 5)), "zero size"),
        (cand("Next: confirm and pay"), "blocked word"),
    ],
)
def test_unusable_controls_rejected(c, reason):
    sel = choose_target([c], NEXT, WINDOW)
    assert sel.target is None
    assert sel.rejected == [(c, reason)]


def test_identical_duplicates_choose_nearest_cursor():
    top, bottom = cand("Next", y=100), cand("Next", y=1000)
    sel = choose_target([top, bottom], NEXT, WINDOW, cursor=(900, 950))
    assert sel.target.candidate is bottom
    sel = choose_target([top, bottom], NEXT, WINDOW, cursor=(900, 50))
    assert sel.target.candidate is top


def test_different_targets_are_ambiguous():
    sel = choose_target([cand("Next chapter", y=200), cand("Next page", y=800)], NEXT, WINDOW)
    assert sel.target is None and sel.reason.startswith("ambiguous")


def test_clear_winner_is_not_ambiguous():
    # "Next" (100) vs arrow-only "›" (70): margin is large enough.
    sel = choose_target([cand("Next chapter", y=200), cand("›", y=800)], NEXT, WINDOW)
    assert sel.target.candidate.name == "Next chapter"


def test_plain_next_compatible_with_next_page():
    sel = choose_target([cand("Next", y=200), cand("Next page", y=800)], NEXT, WINDOW)
    assert sel.target.candidate.name == "Next"


def test_below_min_score():
    # Unnamed control identified only by id scores 60; raise the bar to 70.
    c = cand("", automation_id="nextBtn", kind=ControlKind.LINK)
    assert choose_target([c], NEXT, WINDOW).target is not None
    sel = choose_target([c], NEXT, WINDOW, ScoringOptions(min_score=70))
    assert sel.target is None and "scored" in sel.reason


def test_symbol_button_with_tooltip():
    c = cand("›", help_text="Next image", kind=ControlKind.BUTTON)
    sel = choose_target([c], NEXT, WINDOW)
    assert sel.target is not None


def test_button_preferred_over_menu_item():
    menu = cand("Next", kind=ControlKind.MENU_ITEM, y=100)
    btn = cand("Next", kind=ControlKind.BUTTON, y=900)
    sel = choose_target([menu, btn], NEXT, WINDOW, cursor=(900, 100))
    assert sel.target.candidate is btn


def test_previous_direction():
    sel = choose_target([cand("‹ Previous", x=700), cand("Next ›")], PREV, WINDOW)
    assert sel.target.candidate.name == "‹ Previous"
