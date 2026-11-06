"""Idle character rules: eye shapes, accents, breath and look intensity. Headless, with seeded randomness."""
import importlib
import math
import random
import sys

import pytest

import orb_character
from orb_character import (
    ACCENTS,
    EYE_POINTS,
    EYE_SHAPES,
    STATE_LOOK,
    accent_seconds,
    accent_timeline,
    breath_batch,
    breath_speed,
    eye_shape,
    look_intensity,
    next_accent_delay,
    pick_accent,
)
from orb_motion import BREATH_SCALE_X, BREATH_SCALE_Y, CLIP_FPS

EYE = 11.0
EXPECTED_LOOK = {
    "blink": 1.0, "blink_stagger": 1.0, "double_blink": 1.0, "look_around": 0.0,
    "yawn": 0.0, "bounce": 0.5, "jiggle": 1.0, "happy": 0.0, "wave": 0.5, "balance_eyes": 0.2,
}
EXPECTED_WEIGHT = {
    "blink": 30, "blink_stagger": 15, "double_blink": 10, "look_around": 12,
    "yawn": 6, "bounce": 8, "jiggle": 4, "happy": 8, "wave": 5, "balance_eyes": 2,
}


def _bezier_midpoint(p0, p1, p2, p3):
    return tuple((a + 3 * b + 3 * c + d) / 8.0 for a, b, c, d in zip(p0, p1, p2, p3))


@pytest.mark.parametrize('name', sorted(EYE_SHAPES))
def test_every_eye_shape_has_the_same_point_count(name):
    assert len(eye_shape(name, EYE)) == EYE_POINTS == 13


@pytest.mark.parametrize('size', [7.0, EYE])
@pytest.mark.parametrize('name', sorted(EYE_SHAPES))
def test_every_eye_shape_stays_inside_the_eye_bounds(name, size):
    for x, y in eye_shape(name, size):
        assert -1e-9 <= x <= size + 1e-9
        assert -1e-9 <= y <= size + 1e-9


def test_open_eye_is_a_cream_bar_through_its_segment_midpoints():
    # Restored from 1c63b74: a 4 x 10 pt bar centred in the 11 pt eye frame, so an ellipse of radii 2 and 5.
    points = eye_shape("open", EYE)
    cx, cy = EYE / 2.0, EYE / 2.0
    rx, ry = 2.0, 5.0
    for i in range(1, len(points), 3):
        mid = _bezier_midpoint(points[i - 1], points[i], points[i + 1], points[i + 2])
        assert math.hypot((mid[0] - cx) / rx, (mid[1] - cy) / ry) == pytest.approx(1.0, rel=0.02)


def test_eye_shape_rejects_unknown_names():
    with pytest.raises(ValueError):
        eye_shape("bogus", EYE)


def test_accent_table_matches_the_plan():
    assert {accent.name: accent.weight for accent in ACCENTS} == EXPECTED_WEIGHT
    assert {accent.name: accent.look for accent in ACCENTS} == EXPECTED_LOOK


def test_accent_lengths_in_seconds_at_sixty_fps():
    assert accent_seconds("blink") == pytest.approx(0.333, abs=0.001)
    assert accent_seconds("blink_stagger") == pytest.approx(0.467, abs=0.001)
    assert accent_seconds("double_blink") == pytest.approx(0.7)
    assert accent_seconds("look_around") == pytest.approx(1.5)
    assert accent_seconds("yawn") == pytest.approx(1.6)
    assert accent_seconds("bounce") == pytest.approx(0.6)
    assert accent_seconds("jiggle") == pytest.approx(0.5)
    assert accent_seconds("happy") == pytest.approx(1.0)


@pytest.mark.parametrize('accent', ACCENTS, ids=lambda accent: accent.name)
def test_accent_timelines_end_at_their_length_and_use_known_shapes(accent):
    timeline = accent_timeline(accent.name)
    assert timeline
    for track in timeline.values():
        times = [t for t, _ in track]
        assert times == sorted(times)
        assert times[0] >= 0.0
        assert times[-1] == pytest.approx(accent_seconds(accent.name))
        for t, value in track:
            if isinstance(value, str):
                assert value in EYE_SHAPES


def test_blink_closes_half_way_and_opens_again():
    track = accent_timeline("blink")["eyes_L"]
    assert track[0] == (0.0, "open")
    assert track[1][1] == "closedDown"
    assert track[1][0] == pytest.approx(accent_seconds("blink") / 2.0)
    assert track[-1][1] == "open"


def test_bounce_hops_six_points_and_squashes_on_landing():
    body_y = accent_timeline("bounce")["body_y"]
    assert max(v for _, v in body_y) == pytest.approx(6.0, abs=0.1)
    assert body_y[-1][1] == pytest.approx(0.0)
    squash = accent_timeline("bounce")["body_sy"]
    assert min(v for _, v in squash) == pytest.approx(0.94, abs=0.002)
    assert squash[-1][1] == pytest.approx(1.0, abs=0.01)


def test_jiggle_stays_within_four_percent():
    values = [v for _, v in accent_timeline("jiggle")["body_scale"]]
    assert max(abs(v - 1.0) for v in values) <= 0.04 + 1e-9
    assert values[0] == pytest.approx(1.04)


def test_next_accent_delay_is_uniform_in_four_to_nine_seconds():
    rng = random.Random(7)
    delays = [next_accent_delay(rng) for _ in range(1000)]
    assert all(4.0 <= d <= 9.0 for d in delays)
    assert min(delays) < 4.5 and max(delays) > 8.5


def test_pick_accent_never_repeats_the_previous_accent():
    rng = random.Random(11)
    previous = None
    for _ in range(5000):
        choice = pick_accent(rng, previous)
        assert choice != previous
        previous = choice


def test_pick_accent_matches_weights_within_five_percent():
    rng = random.Random(42)
    total = sum(EXPECTED_WEIGHT.values())
    counts = {name: 0 for name in EXPECTED_WEIGHT}
    draws = 200000  # the rarest accent is 4%; 5% relative needs this many draws to be meaningful
    for _ in range(draws):
        counts[pick_accent(rng)] += 1
    for name, weight in EXPECTED_WEIGHT.items():
        expected = weight / float(total)
        assert counts[name] / float(draws) == pytest.approx(expected, rel=0.05), name


def test_pick_accent_with_no_repeat_keeps_blinks_most_common():
    # The no-repeat rule removes the previous accent, so the chained frequencies drift from the weights.
    # Blinks stay the most common accent, and the drift is measured here rather than hidden.
    rng = random.Random(5)
    previous = None
    counts = {name: 0 for name in EXPECTED_WEIGHT}
    for _ in range(20000):
        previous = pick_accent(rng, previous)
        counts[previous] += 1
    assert max(counts, key=counts.get) == "blink"
    assert counts["blink"] / 20000.0 > 0.2


def test_breath_speed_is_uniform_in_half_to_one_point_three():
    rng = random.Random(3)
    speeds = [breath_speed(rng) for _ in range(1000)]
    assert all(0.5 <= s <= 1.3 for s in speeds)
    assert min(speeds) < 0.6 and max(speeds) > 1.2


def test_breath_batch_cycles_last_between_the_slowest_and_fastest_speed():
    rng = random.Random(9)
    timeline = breath_batch(rng, count=8)
    base = 450 / float(CLIP_FPS)
    ends = [t for t, _, _ in timeline]
    cycles = [b - a for a, b in zip(ends[::2][:-1], ends[::2][1:])]
    assert len(cycles) == 8
    assert all(base / 1.3 - 1e-9 <= c <= base / 0.5 + 1e-9 for c in cycles)
    assert timeline[0][1:] == (1.0, 1.0)
    assert timeline[-1][1:] == (1.0, 1.0)
    peaks = [(sx, sy) for _, sx, sy in timeline if (sx, sy) != (1.0, 1.0)]
    assert set(peaks) == {(BREATH_SCALE_X, BREATH_SCALE_Y)}


@pytest.mark.parametrize('accent', ACCENTS, ids=lambda accent: accent.name)
def test_look_intensity_matches_the_table_for_each_accent(accent):
    assert look_intensity("idle", accent.name) == EXPECTED_LOOK[accent.name]


@pytest.mark.parametrize('state', sorted(STATE_LOOK))
def test_look_intensity_matches_the_state_table(state):
    assert look_intensity(state) == STATE_LOOK[state]


def test_look_intensity_falls_back_to_one_for_unknown_states():
    assert look_intensity("error") == 1.0


def test_character_module_imports_with_no_appkit_or_quartz(monkeypatch):
    for blocked in ('AppKit', 'Quartz', 'Foundation', 'objc'):
        monkeypatch.setitem(sys.modules, blocked, None)
    monkeypatch.delitem(sys.modules, 'orb_character', raising=False)
    module = importlib.import_module('orb_character')
    assert module.__name__ == 'orb_character'
    assert orb_character.HANDLE > 0
