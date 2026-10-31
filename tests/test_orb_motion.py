"""Orb geometry, palette and pupil rules, headless. No AppKit, Quartz or Cocoa."""
import importlib
import itertools
import math
import sys

import pytest

import orb_motion
from orb_motion import (
    BODY_SIZE,
    BOB_AMPLITUDE,
    BOB_PERIOD,
    BREATH_FRAMES,
    CLIP_FPS,
    FLOAT_FRAMES,
    ORB_PALETTE,
    SHADOW_MIN_SCALE,
    cursor_moved,
    idle_active,
    layer_geometry,
    pupil_offset,
    sample_track,
    shadow_for_bob,
    sine_samples,
    spring_decay,
)

BODY_CENTER = (36.0, 36.0)
BODY_RADIUS = BODY_SIZE / 2.0
BOBS = [i / 10.0 for i in range(-25, 26)]


def _inside_body(x, y, bob):
    return math.hypot(x - BODY_CENTER[0], y - (BODY_CENTER[1] + bob)) <= BODY_RADIUS + 1e-9


def _ellipse_points(x, y, w, h, steps=72):
    cx, cy, a, b = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
    for k in range(steps):
        t = 2.0 * math.pi * k / steps
        yield cx + a * math.cos(t), cy + b * math.sin(t)


@pytest.mark.parametrize('bob', BOBS)
def test_eyes_and_pupils_stay_inside_the_body_for_every_bob(bob):
    frames = layer_geometry(bob)
    for name in ('eyeL', 'eyeR', 'pupilL', 'pupilR'):
        x, y, w, h = frames[name]
        for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
            assert _inside_body(cx, cy, bob), (name, bob)


@pytest.mark.parametrize('bob', BOBS)
def test_highlight_stays_inside_the_body_for_every_bob(bob):
    x, y, w, h = layer_geometry(bob)['highlight']
    assert all(_inside_body(px, py, bob) for px, py in _ellipse_points(x, y, w, h))


def test_body_is_centred_and_bob_moves_only_the_body_group():
    frames = layer_geometry(0.0)
    body = frames['body']
    assert body[2] == body[3] == BODY_SIZE
    assert body[0] + body[2] / 2.0 == BODY_CENTER[0]
    assert body[1] + body[3] / 2.0 == BODY_CENTER[1]
    bobbed = layer_geometry(2.5)
    assert bobbed['body'][1] == frames['body'][1] + 2.5
    assert bobbed['highlight'] == frames['highlight']
    assert bobbed['shadow'] == frames['shadow']


def test_pupils_are_centred_in_their_eyes_at_rest():
    frames = layer_geometry(0.0)
    for side in ('L', 'R'):
        ex, ey, ew, eh = frames['eye' + side]
        px, py, pw, ph = frames['pupil' + side]
        assert math.isclose(px + pw / 2.0, ex + ew / 2.0)
        assert math.isclose(py + ph / 2.0, ey + eh / 2.0)


def test_pupil_offset_is_zero_at_distance_zero():
    assert pupil_offset((10.0, 10.0), (10.0, 10.0)) == (0.0, 0.0)


@pytest.mark.parametrize('cursor, sign', [
    ((110.0, 110.0), (1, 1)),
    ((-90.0, 110.0), (-1, 1)),
    ((-90.0, -90.0), (-1, -1)),
    ((110.0, -90.0), (1, -1)),
])
def test_pupil_offset_points_toward_the_cursor_in_every_quadrant(cursor, sign):
    dx, dy = pupil_offset((10.0, 10.0), cursor)
    assert dx * sign[0] > 0
    assert dy * sign[1] > 0


def test_pupil_offset_is_clamped_and_scales_with_distance():
    assert math.hypot(*pupil_offset((0.0, 0.0), (5000.0, 0.0))) == pytest.approx(3.0)
    near = math.hypot(*pupil_offset((0.0, 0.0), (30.0, 0.0)))
    far = math.hypot(*pupil_offset((0.0, 0.0), (150.0, 0.0)))
    assert 0.0 < near < far < 3.0
    assert math.hypot(*pupil_offset((0.0, 0.0), (300.0, 0.0))) == pytest.approx(3.0)


@pytest.mark.parametrize('cursor', [
    (float('nan'), 0.0), (0.0, float('inf')), (float('-inf'), float('nan')), (1e308, -1e308),
])
def test_pupil_offset_stays_finite_for_bad_input(cursor):
    dx, dy = pupil_offset((0.0, 0.0), cursor)
    assert math.isfinite(dx) and math.isfinite(dy)
    assert math.hypot(dx, dy) <= 3.0 + 1e-9


def test_palette_is_three_zero_to_one_float_colours():
    assert len(ORB_PALETTE) == 3
    for colour in ORB_PALETTE:
        assert len(colour) == 3
        for channel in colour:
            assert isinstance(channel, float)
            assert 0.0 <= channel <= 1.0


def test_idle_motion_constants_match_the_plan():
    assert BOB_AMPLITUDE == 2.5
    assert BOB_PERIOD == 2.6
    assert SHADOW_MIN_SCALE == 0.94
    assert BREATH_FRAMES == 450
    assert FLOAT_FRAMES == 1500
    assert CLIP_FPS == 60


@pytest.mark.parametrize('visible, motion, docked, asleep', list(itertools.product((False, True), repeat=4)))
def test_idle_active_truth_table(visible, motion, docked, asleep):
    expected = visible and motion and not docked and not asleep
    assert idle_active(visible, motion, docked, asleep) is expected


def test_cursor_moved_respects_the_half_point_threshold():
    assert cursor_moved(None, (10.0, 10.0))
    assert not cursor_moved((10.0, 10.0), (10.0, 10.0))
    assert not cursor_moved((10.0, 10.0), (10.3, 10.3))
    assert cursor_moved((10.0, 10.0), (10.5, 10.0))
    assert cursor_moved((10.0, 10.0), (10.2, 10.2), eps=0.1)
    assert cursor_moved((0.0, 0.0), (float('nan'), 0.0))


def test_shadow_is_smallest_and_faintest_at_the_top_of_the_bob():
    top_scale, top_opacity = shadow_for_bob(BOB_AMPLITUDE)
    bottom_scale, bottom_opacity = shadow_for_bob(-BOB_AMPLITUDE)
    assert top_scale == pytest.approx(SHADOW_MIN_SCALE)
    assert bottom_scale == pytest.approx(1.0)
    assert top_opacity == pytest.approx(0.28 / 0.35)
    assert bottom_opacity == pytest.approx(1.0)


def test_sine_samples_start_and_end_at_rest_and_stay_in_amplitude():
    samples = sine_samples(BOB_PERIOD, BOB_AMPLITUDE)
    assert samples[0] == (0.0, 0.0)
    assert samples[-1][0] == pytest.approx(BOB_PERIOD)
    assert abs(samples[-1][1]) < 1e-9
    assert max(v for _, v in samples) == pytest.approx(BOB_AMPLITUDE, abs=0.05)
    assert min(v for _, v in samples) == pytest.approx(-BOB_AMPLITUDE, abs=0.05)


def test_spring_decay_starts_at_one_and_settles():
    assert spring_decay(500.0, 18.0, 0.0) == pytest.approx(1.0)
    assert abs(spring_decay(500.0, 18.0, 1.0)) < 0.01
    with pytest.raises(ValueError):
        spring_decay(100.0, 100.0, 0.0)


def test_sample_track_ends_exactly_at_the_duration():
    pairs = sample_track(lambda t: t, 0.6)
    assert pairs[0] == (0.0, 0.0)
    assert pairs[-1][0] == 0.6
    assert len(pairs) == 37  # 36 frames at 60 fps, plus the endpoint


@pytest.mark.parametrize('module_name', ['orb_motion', 'orb_layers', 'orb_character'])
def test_motion_modules_import_with_no_appkit_or_quartz(monkeypatch, module_name):
    for blocked in ('AppKit', 'Quartz', 'Foundation', 'objc'):
        monkeypatch.setitem(sys.modules, blocked, None)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name
    assert orb_motion.DESIGN_SIZE == 72.0


# PR 3a: press, drag and drop physics.

import orb_motion as om


@pytest.mark.parametrize('stiffness, damping', om.SPRINGS)
def test_every_section_three_spring_is_within_a_quarter_point_by_point_six_seconds(stiffness, damping):
    x, v = om.spring(0.6, 0.0, 40.0, stiffness, damping)
    assert abs(x - 40.0) <= om.SETTLE_EPS
    assert math.isfinite(v)


def test_section_three_springs_are_the_plan_values():
    assert om.SPRING_RELEASE == (500.0, 26.0)
    assert om.SPRING_DROP_JIGGLE == (500.0, 18.0)
    assert om.SPRING_SNAP == (300.0, 24.0)
    assert om.SPRING_FOLLOW == (400.0, 36.0)
    assert om.SPRING_PEEK_IN == (300.0, 22.0)
    assert om.SPRING_PEEK_OUT == (200.0, 26.0)
    assert om.SPRING_CAPTURE_ZONE == (500.0, 40.0)
    assert om.SPRING_MENU_FAN == (500.0, 30.0)
    assert om.SPRING_EXPAND == (400.0, 32.0)
    assert om.PRESS_SCALE == (1.12, 0.88)
    assert om.PRESS_SECONDS == 0.10


@pytest.mark.parametrize('zeta', [0.2, 0.4, 0.64, 0.9])
def test_underdamped_overshoot_matches_the_formula_within_three_percent(zeta):
    stiffness = 100.0
    damping = 2.0 * zeta * math.sqrt(stiffness)
    peak = max(om.spring(i / 1000.0, 0.0, 1.0, stiffness, damping)[0] for i in range(6000))
    expected = math.exp(-math.pi * zeta / math.sqrt(1.0 - zeta * zeta))
    assert abs((peak - 1.0) - expected) <= 0.03


@pytest.mark.parametrize('zeta', [1.0, 1.5, 3.0])
def test_critically_and_over_damped_springs_never_overshoot(zeta):
    stiffness = 100.0
    damping = 2.0 * zeta * math.sqrt(stiffness)
    peak = max(om.spring(i / 1000.0, 0.0, 1.0, stiffness, damping)[0] for i in range(6000))
    assert peak <= 1.0 + 1e-9


@pytest.mark.parametrize('zeta', [0.3, 1.0, 2.0])
def test_spring_velocity_is_the_derivative_of_its_position_in_every_branch(zeta):
    stiffness, h = 100.0, 1e-5
    damping = 2.0 * zeta * math.sqrt(stiffness)
    for t in (0.05, 0.2, 0.7):
        numeric = (om.spring(t + h, 3.0, 1.0, stiffness, damping, v0=2.0)[0]
                   - om.spring(t - h, 3.0, 1.0, stiffness, damping, v0=2.0)[0]) / (2.0 * h)
        assert om.spring(t, 3.0, 1.0, stiffness, damping, v0=2.0)[1] == pytest.approx(numeric, rel=1e-3, abs=1e-3)


def test_spring_starts_where_it_was_released_and_settles_on_the_target():
    assert om.spring(0.0, 5.0, 9.0, 300.0, 24.0, v0=-3.0) == (5.0, -3.0)
    x, v = om.spring(10.0, 5.0, 9.0, 300.0, 24.0)
    assert x == pytest.approx(9.0, abs=1e-9)
    assert abs(v) < 1e-9


def test_spring_done_needs_both_position_and_speed():
    assert om.spring_done(10.1, 0.5, 10.0)
    assert not om.spring_done(10.4, 0.0, 10.0)
    assert not om.spring_done(10.0, 20.0, 10.0)


@pytest.mark.parametrize('dt', [1.0 / 30.0, 1.0 / 120.0])
def test_follow_step_converges_and_stays_stable(dt):
    pos, vel = (0.0, 0.0), (0.0, 0.0)
    worst = 0.0
    for _ in range(int(3.0 / dt)):
        pos, vel = om.follow_step(pos, vel, (100.0, -40.0), dt)
        worst = max(worst, abs(pos[0] - 100.0))
    assert abs(pos[0] - 100.0) <= om.SETTLE_EPS
    assert abs(pos[1] + 40.0) <= om.SETTLE_EPS
    assert worst < 110.0  # no blow-up: overshoot stays small at both frame rates


def test_follow_step_does_nothing_for_zero_time_and_bad_input_stays_finite():
    assert om.follow_step((1.0, 2.0), (3.0, 4.0), (9.0, 9.0), 0.0) == ((1.0, 2.0), (3.0, 4.0))
    pos, vel = om.follow_step((float('nan'), 0.0), (float('inf'), 0.0), (1.0, 1.0), float('inf'))
    assert all(math.isfinite(v) for v in pos + vel)


def test_drag_stretch_is_round_at_rest_and_capped():
    assert om.drag_stretch(0, 0) == (1.0, 1.0, 0.0)
    for vx, vy in ((1e6, 0.0), (0.0, -5000.0), (float('inf'), 2.0)):
        sx, sy, _ = om.drag_stretch(vx, vy)
        assert sx <= 1.22 + 1e-12
        assert sx * sy == pytest.approx(1.0)


def test_drag_stretch_points_along_the_direction_of_travel():
    _, _, angle = om.drag_stretch(0.0, 1500.0)
    assert angle == pytest.approx(math.pi / 2)
    sx, _, _ = om.drag_stretch(300.0, 0.0)
    assert sx == pytest.approx(1.1)  # 300 / 3000, under the cap
    assert om.drag_stretch(1500.0, 0.0)[0] == pytest.approx(1.22)  # over the cap, so clamped


def test_stretch_matrix_is_round_at_rest_and_keeps_area():
    assert om.stretch_matrix(1.0, 1.0, 0.7) == pytest.approx((1.0, 0.0, 0.0, 1.0))
    a, b, c, d = om.stretch_matrix(1.2, 1.0 / 1.2, 0.4)
    assert a * d - b * c == pytest.approx(1.0)


def test_drag_roughness_counts_sharp_reversals_and_time_above_3500():
    slow_zigzag = [(0.0, 0.0, 0.0), (0.1, 20.0, 0.0), (0.2, 0.0, 0.0), (0.3, 20.0, 0.0), (0.4, 0.0, 0.0)]
    assert om.drag_roughness(slow_zigzag) == (0, 0.0)  # 200 pt/s, under the 300 pt/s reversal floor
    fast = [(0.0, 0.0, 0.0), (0.1, 500.0, 0.0), (0.2, 0.0, 0.0), (0.3, 500.0, 0.0)]
    reversals, seconds = om.drag_roughness(fast)
    assert reversals == 2
    assert seconds == pytest.approx(0.3)  # every segment runs at 5000 pt/s


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_pure_drag_functions_stay_finite_for_nan_and_inf(bad):
    assert all(math.isfinite(v) for v in om.spring(bad, bad, bad, bad, bad, bad, bad))
    assert all(math.isfinite(v) for v in om.spring(1.0, bad, 1.0, 300.0, 24.0, v0=bad))
    pos, vel = om.follow_step((bad, bad), (bad, bad), (bad, bad), bad)
    assert all(math.isfinite(v) for v in pos + vel)
    assert all(math.isfinite(v) for v in om.drag_stretch(bad, bad))
    assert all(math.isfinite(v) for v in om.stretch_matrix(bad, bad, bad))
    reversals, seconds = om.drag_roughness([(bad, bad, bad), (0.0, 1.0, bad), (0.1, 2.0, 2.0)])
    assert math.isfinite(seconds) and reversals >= 0
    assert isinstance(om.spring_done(bad, bad, bad), bool)
