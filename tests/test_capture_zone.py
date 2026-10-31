"""Edge capture zone: geometry, show and hide rules, and slide maths, headless. No AppKit, Quartz or Cocoa."""
import math
import os

import pytest

import capture_zone
from capture_zone import (
    CaptureZone,
    ZONE_EDGES,
    ZONE_H,
    ZONE_HIDE_DISTANCE,
    ZONE_RADIUS,
    ZONE_SHOW_DISTANCE,
    ZONE_TEXT,
    ZONE_W,
    ease_in,
    inward_distance,
    is_outer_edge,
    screen_at,
    zone_frame,
    zone_offset,
    zone_slide_in,
    zone_slide_out,
    zone_state,
    zone_travel,
)

SCREEN = (0.0, 0.0, 1440.0, 900.0)
SLOW = (0.0, 0.0)
FAST_RIGHT = (2000.0, 0.0)
FAST_LEFT = (-2000.0, 0.0)
FAST_UP = (0.0, 2000.0)
FAST_DOWN = (0.0, -2000.0)


def _state(prev, cursor, velocity=SLOW, screen=SCREEN, screens=None):
    return zone_state(prev, cursor, velocity, screen, [SCREEN] if screens is None else screens)


def test_text_constant_is_exact():
    assert ZONE_TEXT == "Drag to capture · Esc to cancel"
    assert (ZONE_W, ZONE_H, ZONE_RADIUS) == (260.0, 56.0, 14.0)


def test_shows_at_four_points_from_each_outer_edge():
    assert _state(None, (1440.0 - 4.0, 450.0)) == "right"
    assert _state(None, (4.0, 450.0)) == "left"
    assert _state(None, (700.0, 900.0 - 4.0)) == "top"
    assert _state(None, (700.0, 4.0)) == "bottom"


def test_does_not_show_in_the_middle_of_the_screen():
    assert _state(None, (700.0, 450.0)) is None
    assert _state(None, (1440.0 - 5.0, 450.0)) is None


def test_shows_on_a_fast_approach_inside_forty_points():
    assert _state(None, (1440.0 - 30.0, 450.0), FAST_RIGHT) == "right"
    assert _state(None, (30.0, 450.0), FAST_LEFT) == "left"
    assert _state(None, (700.0, 900.0 - 30.0), FAST_UP) == "top"
    assert _state(None, (700.0, 30.0), FAST_DOWN) == "bottom"


def test_fast_approach_needs_to_be_inside_forty_points_and_moving_toward_the_edge():
    assert _state(None, (1440.0 - 60.0, 450.0), FAST_RIGHT) is None
    assert _state(None, (1440.0 - 30.0, 450.0), FAST_LEFT) is None
    assert _state(None, (1440.0 - 30.0, 450.0), (1400.0, 0.0)) is None


def test_no_flicker_between_four_and_eighty_points():
    shown = _state(None, (4.0, 450.0))
    assert shown == "left"
    for x in (5.0, 20.0, 45.0, 60.0, 79.0, ZONE_HIDE_DISTANCE):
        shown = _state(shown, (x, 450.0))
        assert shown == "left", x


def test_hides_beyond_eighty_points():
    shown = _state(None, (4.0, 450.0))
    assert _state(shown, (ZONE_HIDE_DISTANCE + 0.5, 450.0)) is None


def test_stays_shown_when_the_cursor_is_past_the_edge():
    assert _state("left", (-200.0, 450.0)) == "left"


def test_never_shown_on_an_inner_shared_edge():
    left_screen = (-1440.0, 0.0, 1440.0, 900.0)
    screens = [SCREEN, left_screen]
    # The right edge of SCREEN touches nothing, so it is outer. The left edge touches left_screen.
    assert _state(None, (4.0, 450.0), screens=screens, screen=SCREEN) is None
    assert _state(None, (1440.0 - 4.0, 450.0), screens=screens, screen=SCREEN) == "right"
    # Seen from the other screen, its right edge is the shared one.
    assert _state(None, (-4.0, 450.0), screens=screens, screen=left_screen) is None


def test_inner_edge_test_ignores_displays_that_do_not_overlap_the_span():
    # A display above and to the right touches only at a corner, so the right edge stays outer.
    above_right = (1440.0, 900.0, 1440.0, 900.0)
    assert is_outer_edge("right", SCREEN, [SCREEN, above_right]) is True
    # But the top edge is shared with a display directly above, and it is not outer.
    above = (0.0, 900.0, 1440.0, 900.0)
    assert is_outer_edge("top", SCREEN, [SCREEN, above]) is False
    assert is_outer_edge("bottom", SCREEN, [SCREEN, above]) is True


def test_is_outer_edge_rejects_unknown_edges_and_bad_screens():
    assert is_outer_edge("diagonal", SCREEN, [SCREEN]) is False
    assert is_outer_edge("left", None, [SCREEN]) is False
    assert is_outer_edge("left", (0, 0, 0, 0), [SCREEN]) is False


def test_bad_input_hides_the_zone():
    assert _state(None, (float("nan"), 450.0)) is None
    assert _state(None, (4.0, 450.0), screen=None) is None
    assert _state(None, (4.0, 450.0), velocity=(float("inf"), 0.0)) == "left"
    assert _state(None, (4.0, 450.0), velocity=("x", "y")) == "left"


def test_nearest_edge_wins_in_a_corner():
    assert _state(None, (3.0, 897.0)) == "left"
    assert _state(None, (1.0, 899.0)) == "left"


def test_screen_at_finds_the_containing_frame():
    left = (-1000.0, 0.0, 1000.0, 800.0)
    assert screen_at((-500.0, 100.0), [SCREEN, left]) == left
    assert screen_at((500.0, 100.0), [SCREEN, left]) == SCREEN
    assert screen_at((5000.0, 100.0), [SCREEN, left]) is None
    assert screen_at((float("nan"), 1.0), [SCREEN]) is None


def test_inward_distance_is_positive_inside_and_negative_past_the_edge():
    assert inward_distance("left", (10.0, 0.0), SCREEN) == 10.0
    assert inward_distance("left", (-10.0, 0.0), SCREEN) == -10.0
    assert inward_distance("right", (1430.0, 0.0), SCREEN) == 10.0
    assert inward_distance("bottom", (0.0, 7.0), SCREEN) == 7.0
    assert inward_distance("top", (0.0, 893.0), SCREEN) == 7.0
    with pytest.raises(ValueError):
        inward_distance("nowhere", (0.0, 0.0), SCREEN)


def test_frame_sits_flush_with_the_edge_and_centred_on_the_cursor_along_it():
    assert zone_frame("left", (4.0, 450.0), SCREEN) == (0.0, 450.0 - 28.0, ZONE_W, ZONE_H)
    assert zone_frame("right", (1436.0, 300.0), SCREEN) == (1440.0 - ZONE_W, 300.0 - 28.0, ZONE_W, ZONE_H)
    assert zone_frame("bottom", (700.0, 4.0), SCREEN) == (700.0 - ZONE_W / 2.0, 0.0, ZONE_W, ZONE_H)
    assert zone_frame("top", (700.0, 896.0), SCREEN) == (700.0 - ZONE_W / 2.0, 900.0 - ZONE_H, ZONE_W, ZONE_H)


@pytest.mark.parametrize("edge, cursor", [
    ("left", (0.0, 2.0)),
    ("left", (0.0, 898.0)),
    ("right", (1440.0, 0.0)),
    ("right", (1440.0, 899.0)),
    ("bottom", (0.0, 0.0)),
    ("bottom", (1439.0, 0.0)),
    ("top", (0.0, 900.0)),
    ("top", (1439.0, 900.0)),
])
def test_frame_is_clamped_inside_the_visible_frame(edge, cursor):
    x, y, w, h = zone_frame(edge, cursor, SCREEN)
    assert SCREEN[0] <= x and x + w <= SCREEN[0] + SCREEN[2]
    assert SCREEN[1] <= y and y + h <= SCREEN[1] + SCREEN[3]


def test_frame_is_clamped_on_a_small_screen_with_a_negative_origin():
    small = (-800.0, -300.0, 300.0, 200.0)  # narrower than the zone, so it cannot fit flush on both sides
    x, y, w, h = zone_frame("left", (-795.0, -290.0), small)
    assert x == -800.0  # flush with the screen's own left edge
    x, y, w, h = zone_frame("right", (-795.0, -290.0), small)
    assert x == -800.0 + 300.0 - ZONE_W  # flush with the right edge, -760
    assert small[1] <= y and y + h <= small[1] + small[3]
    short = (-800.0, -300.0, 1000.0, 40.0)  # shorter than the zone
    _, y, _, h = zone_frame("left", (-700.0, -290.0), short)
    assert y == -300.0


def test_frame_rejects_bad_edges_and_input():
    assert zone_frame("middle", (0.0, 0.0), SCREEN) is None
    assert zone_frame("left", (float("inf"), 0.0), SCREEN) is None
    assert zone_frame("left", (0.0, 0.0), None) is None


def test_travel_and_offset_match_the_edge():
    assert zone_travel("left") == ZONE_W
    assert zone_travel("top") == ZONE_H
    assert zone_offset("left", 10.0) == (-10.0, 0.0)
    assert zone_offset("right", 10.0) == (10.0, 0.0)
    assert zone_offset("bottom", 10.0) == (0.0, -10.0)
    assert zone_offset("top", 10.0) == (0.0, 10.0)
    with pytest.raises(ValueError):
        zone_travel("middle")


def test_slide_in_starts_at_its_offset_and_lands_exactly_at_the_end():
    assert zone_slide_in(260.0, 0.0) == pytest.approx(260.0)
    assert zone_slide_in(260.0, capture_zone.ZONE_SLIDE_IN_SECONDS) == 0.0
    assert zone_slide_in(260.0, 5.0) == 0.0
    mid = zone_slide_in(260.0, 0.05)
    assert 0.0 < mid < 260.0 and math.isfinite(mid)


def test_slide_out_eases_in_from_start_to_travel():
    assert zone_slide_out(0.0, 260.0, 0.0) == 0.0
    assert zone_slide_out(0.0, 260.0, capture_zone.ZONE_SLIDE_OUT_SECONDS) == pytest.approx(260.0)
    half = zone_slide_out(0.0, 260.0, capture_zone.ZONE_SLIDE_OUT_SECONDS / 2.0)
    assert half == pytest.approx(260.0 * 0.25)  # quadratic ease-in, so it is slow at first
    assert zone_slide_out(0.0, 260.0, 10.0) == pytest.approx(260.0)


def test_ease_in_clamps_and_is_quadratic():
    assert ease_in(-1.0) == 0.0
    assert ease_in(2.0) == 1.0
    assert ease_in(0.5) == 0.25


def test_every_edge_is_known_to_the_state_machine():
    for edge in ZONE_EDGES:
        assert edge in ("left", "right", "top", "bottom")
    assert ZONE_SHOW_DISTANCE == 4.0


class FakePanel:
    """Records what the zone asked the panel to do. Stands in for CaptureZonePanel."""

    def __init__(self, orb_window):
        self.orb_window = orb_window
        self.calls = []
        self.frame = None

    def order_below(self, orb_window):
        self.calls.append(("below", orb_window))

    def set_frame(self, frame):
        self.frame = frame
        self.calls.append(("frame", frame))

    def order_out(self):
        self.calls.append(("out",))


REST = (0.0, 422.0, ZONE_W, ZONE_H)
ORB = "orb-window"


def _zone():
    made = []

    def make(orb_window):
        panel = FakePanel(orb_window)
        made.append(panel)
        return panel

    zone = CaptureZone(make)
    zone.made = made
    return zone


def test_first_show_builds_one_panel_and_orders_it_below_the_orb():
    zone = _zone()
    zone.show("left", REST, ORB, 0.0)
    assert len(zone.made) == 1
    assert ("below", ORB) in zone.made[0].calls
    zone.show("left", REST, ORB, 0.01)  # already showing: no second order, no second panel
    assert len(zone.made) == 1
    assert [c for c in zone.made[0].calls if c[0] == "below"] == [("below", ORB)]


def test_slide_in_starts_travel_outside_and_lands_on_the_rest_frame():
    zone = _zone()
    zone.show("left", REST, ORB, 0.0)
    panel = zone.made[0]
    dx0 = panel.frame[0] - REST[0]
    assert dx0 == pytest.approx(-ZONE_W)  # starts fully outside on the left
    zone.step(0.1)
    assert REST[0] - ZONE_W < panel.frame[0] < REST[0]
    zone.step(capture_zone.ZONE_SLIDE_IN_SECONDS)
    assert panel.frame == REST
    assert zone.anim is None


def test_retract_slides_out_then_hides_the_panel():
    zone = _zone()
    zone.show("right", REST, ORB, 0.0)
    zone.step(0.5)
    zone.retract(1.0)
    assert zone.retracting is True
    assert zone.visible_for_drop() is False
    zone.step(1.0 + capture_zone.ZONE_SLIDE_OUT_SECONDS / 2.0)
    assert zone.showing is True  # still on the way out
    zone.step(1.0 + capture_zone.ZONE_SLIDE_OUT_SECONDS + 0.01)
    assert ("out",) in zone.made[0].calls
    assert zone.showing is False and zone.edge is None


def test_reshow_during_retract_slides_back_in_from_where_it_was():
    zone = _zone()
    zone.show("left", REST, ORB, 0.0)
    zone.step(0.22)
    zone.retract(1.0)
    zone.step(1.05)
    partway = zone.offset
    assert 0.0 < partway < ZONE_W
    zone.show("left", REST, ORB, 1.05)
    assert zone.retracting is False
    assert zone.anim == ("in", 1.05, partway)
    assert [c for c in zone.made[0].calls if c[0] == "below"] == [("below", ORB)]  # not ordered again


def test_switching_edges_flies_in_from_the_new_edge():
    zone = _zone()
    zone.show("left", REST, ORB, 0.0)
    zone.show("top", (300.0, 800.0, ZONE_W, ZONE_H), ORB, 0.5)
    assert zone.edge == "top"
    assert zone.offset == ZONE_H  # the top zone's travel, not the left one's
    assert zone.anim == ("in", 0.5, ZONE_H)


def test_retract_when_hidden_is_a_no_op():
    zone = _zone()
    zone.retract(0.0)
    assert zone.anim is None and zone.retracting is False
    assert zone.made == []


def test_step_without_a_panel_or_animation_does_nothing():
    zone = _zone()
    zone.step(3.0)
    assert zone.made == []


def test_hide_now_resets_everything_for_the_next_drag():
    zone = _zone()
    zone.show("bottom", (100.0, 0.0, ZONE_W, ZONE_H), ORB, 0.0)
    zone.retract(0.1)
    zone.hide_now()
    assert zone.edge is None and zone.rest is None and zone.anim is None
    assert zone.offset == 0.0 and zone.retracting is False and zone.showing is False
    assert ("out",) in zone.made[0].calls


def test_drop_state_reflects_the_zone_being_fully_shown():
    zone = _zone()
    assert zone.visible_for_drop() is False
    zone.show("right", REST, ORB, 0.0)
    assert zone.visible_for_drop() is True
    zone.retract(0.1)
    assert zone.visible_for_drop() is False


def test_the_panel_is_placed_before_it_is_ordered_front():
    zone = _zone()
    zone.show("left", REST, ORB, 0.0)
    names = [c[0] for c in zone.made[0].calls]
    assert names.index("frame") < names.index("below")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _source(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_a_capture_drop_springs_home_without_re_tucking_the_orb():
    ui = _source("assistant_ui.py")
    # The landing finalizes with peek=False, so _peek_consider cannot re-tuck and latch the orb.
    assert 'delegate._finalize_mini_bar_drag(state["window"], peek=not home)' in ui
    assert "if peek:\n            self._peek_consider()" in ui
    # The reduce-motion path follows the same rule.
    assert "delegate._finalize_mini_bar_drag(window, peek=not home)" in ui


def test_the_capture_landing_brings_the_orb_back_into_view():
    ui = _source("assistant_ui.py")
    landed = ui.split("def _capture_zone_landed(self):", 1)[1].split("@objc.python_method", 1)[0]
    assert "self._apply_bar_visibility()" in landed
