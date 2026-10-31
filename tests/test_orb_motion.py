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
