"""Original orb rules; no Cocoa, microphone, services or credentials."""
import math
import pytest
from mini_bar import (
    ORB_EDGE_INSET,
    ORB_PANEL,
    ORB_SNAP_BAND,
    capsule_click_moved,
    clamp_origin,
    expanded_frame_from_capsule,
    finish_drag,
    migrate_saved_origin,
    reset_origin,
    snap_origin,
)
from orb_view import OrbTicker, orb_frame, orb_pose, orb_state

AIR = (0.0, 70.0, 1440.0, 806.0)
LEFT = (-1920.0, 0.0, 1920.0, 1080.0)


@pytest.mark.parametrize('status, expected', [
    ('Ready', 'idle'), ('Listening', 'listening'), ('Dictating', 'listening'),
    ('Transcribing', 'thinking'), ('Thinking', 'thinking'), ('Doing it', 'thinking'),
    ('Finishing', 'thinking'), ('Speaking', 'speaking'),
    ("Time's up", 'error'), ('Something went wrong', 'error'), ('unknown', 'idle'),
])
def test_status_mapping_and_hold_priority(status, expected):
    assert orb_state(status) == expected
    assert orb_state(status, held=True) == 'listening'


@pytest.mark.parametrize('state', ['idle', 'listening', 'thinking', 'speaking', 'error'])
def test_reduce_motion_freezes_all_decorative_motion(state):
    assert orb_pose(state, 0, 0, True) == orb_pose(state, 6.9, 1, True)


def test_idle_pose_is_static_and_thinking_sweep_and_audio_bounds():
    # Bob runs in the render server, and blinks are random accents, so the pose never blinks on a fixed beat.
    assert all(orb_pose('idle', t)[0] == 0.0 for t in (0, 1, 6.9))
    assert all(orb_pose('idle', t)[1] == 1.0 for t in (0, 6.9, 7.0, 14.0))
    assert orb_pose('thinking', 0.75)[2] == pytest.approx(8)
    assert orb_pose('listening', 0, -5)[3] == 2
    assert orb_pose('listening', 0, 5)[3] == 4
    assert all(math.isfinite(v) for v in orb_pose('listening', 0, float('nan')))


@pytest.mark.parametrize('box', [(80, 140, 420, 44), (-1000, 80, 280, 40), (1600, 500, 720, 64)])
def test_orb_keeps_existing_anchor_and_composer_size(box):
    orb = orb_frame(box)
    assert orb[2:] == (72, 72)
    assert expanded_frame_from_capsule(orb, box[2:]) == box


def test_timer_is_single_and_stops_on_every_inactive_transition():
    created = []
    class Timer:
        invalidated = False
        def invalidate(self):
            self.invalidated = True
    def schedule():
        timer = Timer()
        created.append(timer)
        return timer
    ticker = OrbTicker()
    for _reason in ('hidden', 'expanded', 'reduce_motion', 'quit'):
        ticker.sync(True, schedule)
        current = ticker.timer
        ticker.sync(True, schedule)
        assert ticker.timer is current
        ticker.sync(False, schedule)
        assert current.invalidated
        assert ticker.timer is None
        ticker.sync(False, schedule)
    assert len(created) == 4


def test_single_shot_ticker_schedules_again_only_after_it_fires():
    created = []
    class Timer:
        invalidated = False
        def invalidate(self):
            self.invalidated = True
    def schedule():
        timer = Timer()
        created.append(timer)
        return timer
    ticker = OrbTicker()
    ticker.sync(True, schedule)
    ticker.fired()
    assert ticker.timer is None
    ticker.sync(True, schedule)
    assert len(created) == 2
    assert not created[0].invalidated
    assert ticker.timer is created[1]
    ticker.sync(True, schedule)
    assert len(created) == 2


def test_click_stays_under_four_points_and_drag_does_not():
    assert not capsule_click_moved((10.0, 10.0), (13.0, 10.0))
    assert capsule_click_moved((10.0, 10.0), (15.0, 10.0))


def test_finish_drag_respects_menu_bar_and_dock_visible_frame():
    size = (ORB_PANEL, ORB_PANEL)
    inset = ORB_EDGE_INSET
    sx, sy, sw, sh = AIR
    max_x = sx + sw - ORB_PANEL - inset
    max_y = sy + sh - ORB_PANEL - inset
    assert finish_drag((sx + 5.0, sy + 5.0), size, [AIR]) == (inset, sy + inset)
    assert finish_drag((max_x + 10.0, max_y), size, [AIR]) == (max_x, max_y)
    assert finish_drag((sx - 500.0, sy - 500.0), size, [AIR]) == migrate_saved_origin(
        (9000.0, 9000.0), [AIR], size)


def test_finish_drag_snaps_near_edges_with_twelve_point_inset():
    size = (ORB_PANEL, ORB_PANEL)
    sx, sy, sw, sh = AIR
    inset = ORB_EDGE_INSET
    near_left = (sx + inset + ORB_SNAP_BAND - 1.0, sy + 200.0)
    assert finish_drag(near_left, size, [AIR])[0] == sx + inset
    near_top = (sx + 400.0, sy + sh - ORB_PANEL - inset - ORB_SNAP_BAND + 1.0)
    assert finish_drag(near_top, size, [AIR])[1] == sy + sh - ORB_PANEL - inset
    middle = (sx + sw / 2.0, sy + sh / 2.0)
    placed = finish_drag(middle, size, [AIR])
    assert placed[0] != sx + inset
    assert placed[1] != sy + inset


def test_finish_drag_is_idempotent_so_the_settle_can_finalize_where_it_lands():
    # The settle springs the window to finish_drag's target, then _finalize_mini_bar_drag runs finish_drag again.
    size = (ORB_PANEL, ORB_PANEL)
    sx, sy, sw, sh = AIR
    for origin in ((sx + ORB_EDGE_INSET + 3.0, sy + 200.0), (sx + sw / 2.0, sy + sh / 2.0),
                   (sx + sw - ORB_PANEL, sy + sh - ORB_PANEL - 2.0)):
        once = finish_drag(origin, size, [AIR])
        assert finish_drag(once, size, [AIR]) == once


def test_finish_drag_on_a_negative_coordinate_display():
    size = (ORB_PANEL, ORB_PANEL)
    sx, sy, sw, sh = LEFT
    inset = ORB_EDGE_INSET
    placed = finish_drag((sx + 300.0, sy + 120.0), size, [LEFT])
    assert placed[0] >= sx + inset
    assert placed[1] >= sy + inset
    assert placed[0] <= sx + sw - ORB_PANEL - inset


def test_monitor_disconnect_recovers_to_bottom_center():
    size = (ORB_PANEL, ORB_PANEL)
    saved = (9000.0, 9000.0)
    recovered = finish_drag(saved, size, [AIR])
    default = migrate_saved_origin(saved, [AIR], size)
    assert recovered == default
    assert reset_origin([AIR]) == migrate_saved_origin(None, [AIR])


def test_clamp_and_snap_stay_finite_on_tiny_visible_frames():
    tiny = (0.0, 0.0, ORB_PANEL, ORB_PANEL)
    origin = (100.0, 100.0)
    clamped = clamp_origin(origin, (ORB_PANEL, ORB_PANEL), tiny)
    snapped = snap_origin(origin, (ORB_PANEL, ORB_PANEL), tiny)
    assert all(math.isfinite(v) for v in clamped + snapped)
