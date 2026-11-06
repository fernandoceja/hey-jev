"""PR 7 voice states: resolve, clips, look easing, voice poses and WAV envelopes. Headless, with seeded randomness."""
import array
import math
import random
import sys
import wave

import pytest

from orb_character import (
    CLIPS,
    EYE_SHAPES,
    STATE_CLIPS,
    STATE_LOOK,
    clip_switch_delay,
    ease_look,
    next_clip,
    orb_state,
    resolve,
)
from orb_motion import (
    ENVELOPE_HZ,
    MOUTH_MAX_HEIGHT,
    MOUTH_MIN_HEIGHT,
    PUPIL_LISTEN_SIZE,
    PUPIL_SIZE,
    pulse_mouth,
    squint_scale,
    mouth_height,
    voice_pose,
    wav_envelope,
)


# ---- resolve ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('status, expected', [
    ('Ready', 'idle'), ('idle', 'idle'), ('unknown', 'idle'),
    ('Listening', 'listening'), ('Dictating', 'listening'),
    ('Transcribing', 'thinking'), ('Thinking', 'thinking'), ('Finishing', 'thinking'),
    ('Doing it', 'searching'), ('Speaking', 'speaking'),
    ("Time's up", 'still'), ('Something went wrong', 'still'),
])
def test_resolve_maps_every_status_in_orb_state(status, expected):
    assert resolve(status, False, False, False) == expected


@pytest.mark.parametrize('status', ['Ready', 'Listening', 'Thinking', 'Doing it', 'Speaking', "Time's up"])
def test_hold_wins_and_gives_listening_except_when_reduced(status):
    assert resolve(status, True, False, False) == 'listening'
    assert resolve(status, True, True, False) == 'still'


@pytest.mark.parametrize('status', ['Ready', 'Listening', 'Thinking', 'Doing it', 'Speaking', 'Something went wrong'])
def test_reduce_motion_always_gives_still(status):
    assert resolve(status, False, True, False) == 'still'
    assert resolve(status, True, True, True) == 'still'


@pytest.mark.parametrize('status', ['Ready', 'Listening', 'Thinking', 'Doing it', 'Speaking'])
def test_menu_open_does_not_change_the_state(status):
    assert resolve(status, False, False, True) == resolve(status, False, False, False)


def test_every_resolved_state_is_one_of_the_six_character_states():
    states = set()
    for status in ['Ready', 'Listening', 'Dictating', 'Transcribing', 'Thinking', 'Doing it', 'Finishing',
                   'Speaking', "Time's up", 'Something went wrong', 'other']:
        for held in (False, True):
            for reduce_motion in (False, True):
                states.add(resolve(status, held, reduce_motion, False))
    assert states == {'idle', 'listening', 'thinking', 'searching', 'speaking', 'still'}


def test_orb_state_is_unchanged_and_still_importable_from_orb_view():
    from orb_view import orb_state as from_view
    assert from_view is orb_state
    assert orb_state('Doing it') == 'thinking'
    assert orb_state('Doing it', held=True) == 'listening'


# ---- clips and timing ------------------------------------------------------------------------------------

def test_state_clips_match_the_plan_table():
    assert STATE_CLIPS['listening'] == ('listen_1', 'listen_2', 'listen_3')
    assert STATE_CLIPS['thinking'] == ('think_1', 'think_2', 'think_3')
    assert STATE_CLIPS['searching'] == ('search_1', 'search_2')
    assert STATE_CLIPS['speaking'] == ('talk_1', 'talk_2', 'talk_3', 'talk_4')
    assert STATE_CLIPS['idle'] == () and STATE_CLIPS['still'] == ()


def test_every_clip_named_in_the_table_is_defined_with_known_eye_shapes():
    named = {name for names in STATE_CLIPS.values() for name in names}
    assert named == set(CLIPS)
    for clip in CLIPS.values():
        assert len(clip.eyes) == 2
        assert all(shape in EYE_SHAPES for shape in clip.eyes)
        assert 0.5 <= clip.scale_y <= 1.5


def test_sceptic_is_a_registered_eye_shape_used_by_a_thinking_clip():
    assert 'sceptic' in EYE_SHAPES
    assert any('sceptic' in clip.eyes for clip in CLIPS.values())


@pytest.mark.parametrize('state, expected', [
    ('idle', 1.0), ('listening', 0.6), ('thinking', 0.0), ('searching', 0.3), ('speaking', 0.5), ('still', 0.0),
])
def test_look_intensity_matches_the_state_table(state, expected):
    assert STATE_LOOK[state] == expected


def test_thinking_switches_every_seven_seconds_exactly():
    rng = random.Random(1)
    assert all(clip_switch_delay('thinking', rng) == 7.0 for _ in range(20))


@pytest.mark.parametrize('state, seconds', [('searching', 4.0), ('listening', 3.0)])
def test_fixed_switch_delays(state, seconds):
    assert clip_switch_delay(state, random.Random(2)) == seconds


def test_speaking_switch_delay_is_uniform_between_two_and_four_seconds():
    rng = random.Random(3)
    delays = [clip_switch_delay('speaking', rng) for _ in range(2000)]
    assert all(2.0 <= d <= 4.0 for d in delays)
    mean = sum(delays) / len(delays)
    assert abs(mean - 3.0) < 0.05


@pytest.mark.parametrize('state', ['idle', 'still'])
def test_states_without_a_clip_cycle_have_no_switch_delay_and_no_clip(state):
    rng = random.Random(4)
    assert clip_switch_delay(state, rng) is None
    assert next_clip(state, rng, None) is None


@pytest.mark.parametrize('state', ['listening', 'thinking', 'searching', 'speaking'])
def test_next_clip_never_repeats_the_previous_clip(state):
    rng = random.Random(5)
    previous = None
    for _ in range(300):
        clip = next_clip(state, rng, previous)
        assert clip in STATE_CLIPS[state]
        assert clip != previous
        previous = clip


def test_next_clip_uses_every_clip_of_the_state():
    rng = random.Random(6)
    seen = set()
    previous = None
    for _ in range(400):
        previous = next_clip('speaking', rng, previous)
        seen.add(previous)
    assert seen == set(STATE_CLIPS['speaking'])


def test_ease_look_moves_from_start_to_target_over_a_quarter_second():
    assert ease_look(1.0, 0.0, 0.0) == 1.0
    assert ease_look(1.0, 0.0, 0.25) == 0.0
    assert ease_look(1.0, 0.0, 9.0) == 0.0
    middle = ease_look(1.0, 0.0, 0.125)
    assert middle == pytest.approx(0.5)
    values = [ease_look(0.0, 1.0, t / 100.0) for t in range(0, 26)]
    assert values == sorted(values)


def test_ease_look_stays_finite_for_bad_input():
    assert ease_look(float('nan'), 0.6, 0.1) == pytest.approx(0.6)
    assert ease_look(0.0, float('inf'), 0.1) == 0.0
    assert ease_look('x', 1.0, 0.1) == 0.0


# ---- voice poses -----------------------------------------------------------------------------------------

POSE_KEYS = {'eye_shape', 'eye_scale_y', 'pupil_size', 'pupil_bias', 'body_scale', 'spinner_on', 'mouth_h'}


@pytest.mark.parametrize('state', ['idle', 'listening', 'thinking', 'searching', 'speaking', 'still'])
@pytest.mark.parametrize('t', [0.0, 0.4, 1.1, 2.9, 17.3])
def test_voice_pose_keys_and_bounds_hold_at_every_time(state, t):
    pose = voice_pose(state, t, 0.5)
    assert set(pose) == POSE_KEYS
    assert pose['eye_shape'] in EYE_SHAPES
    assert 0.5 <= pose['eye_scale_y'] <= 1.5
    assert 0.0 < pose['pupil_size'] <= PUPIL_SIZE * 1.5
    bias_x, bias_y = pose['pupil_bias']
    assert abs(bias_x) <= 3.0 and abs(bias_y) <= 3.0
    assert 0.95 <= pose['body_scale'] <= 1.05
    assert MOUTH_MIN_HEIGHT - 1e-9 <= pose['mouth_h'] <= MOUTH_MAX_HEIGHT + 1e-9 or pose['mouth_h'] == 0.0
    assert isinstance(pose['spinner_on'], bool)


def test_listening_pose_is_wide_eyes_with_scaled_pupils_and_a_level_driven_body():
    quiet = voice_pose('listening', 0.0, 0.0)
    loud = voice_pose('listening', 0.0, 1.0)
    assert quiet['eye_shape'] == 'wide' and quiet['eye_scale_y'] == pytest.approx(1.15)
    assert quiet['pupil_size'] == pytest.approx(PUPIL_LISTEN_SIZE)
    assert quiet['body_scale'] == pytest.approx(1.0)
    assert loud['body_scale'] == pytest.approx(1.04)
    assert quiet['spinner_on'] is False


@pytest.mark.parametrize('level, expected', [(-5, 1.0), (0.5, 1.02), (7, 1.04), (float('nan'), 1.0)])
def test_listening_body_scale_is_clamped_and_follows_the_level(level, expected):
    assert voice_pose('listening', 0.0, level)['body_scale'] == pytest.approx(expected)


def test_thinking_and_searching_are_the_only_states_with_a_spinner():
    spinning = {state for state in ['idle', 'listening', 'thinking', 'searching', 'speaking', 'still']
                if voice_pose(state, 0.3, 0.2)['spinner_on']}
    assert spinning == {'thinking', 'searching'}


def test_thinking_pose_biases_the_pupils_up_and_right():
    assert voice_pose('thinking', 0.0, 0.0)['pupil_bias'] == (1.8, 1.8)


def test_speaking_pose_mouth_stays_between_two_and_five_points():
    samples = [voice_pose('speaking', t / 100.0, 0.0)['mouth_h'] for t in range(0, 400)]
    assert min(samples) >= 2.0 - 1e-9 and max(samples) <= 5.0 + 1e-9
    assert max(samples) - min(samples) > 2.9


def test_pulse_mouth_runs_at_three_and_a_half_hertz_between_two_and_five():
    values = [pulse_mouth(i / 1000.0) for i in range(0, 2000)]
    assert min(values) == pytest.approx(2.0, abs=0.01)
    assert max(values) == pytest.approx(5.0, abs=0.01)
    assert pulse_mouth(0.0) == pytest.approx(3.5)
    assert pulse_mouth(1 / 3.5) == pytest.approx(3.5, abs=1e-9)


def test_mouth_height_and_squint_are_clamped():
    assert mouth_height(0.0) == pytest.approx(2.0)
    assert mouth_height(1.0) == pytest.approx(5.0)
    assert mouth_height(9.0) == pytest.approx(5.0)
    assert squint_scale(0.5) == 1.0
    assert squint_scale(1.0) == pytest.approx(0.7)
    assert squint_scale(float('nan')) == 1.0


# ---- WAV envelope ----------------------------------------------------------------------------------------

def _write_wav(path, seconds=2.0, rate=8000, width=2, channels=1, freq=220.0):
    """A sine tone that swells and fades, so the envelope has a shape to check."""
    frames = int(seconds * rate)
    peak = {1: 127, 2: 32000}[width]
    out = array.array('h')
    for n in range(frames):
        t = n / float(rate)
        amp = 0.25 + 0.75 * (0.5 - 0.5 * math.cos(math.tau * t / seconds))
        sample = amp * math.sin(math.tau * freq * t)
        for _ in range(channels):
            out.append(int(sample * peak))
    if width == 2:
        raw = out.tobytes()
    else:
        raw = bytes((int(max(-128, min(127, v))) + 128) & 0xFF for v in out)
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(raw)
    return path


@pytest.mark.parametrize('width, channels', [(1, 1), (2, 1), (1, 2), (2, 2)])
def test_wav_envelope_gives_thirty_values_a_second_between_zero_and_one(tmp_path, width, channels):
    path = _write_wav(tmp_path / 'reply.wav', seconds=2.0, width=width, channels=channels)
    levels = wav_envelope(str(path))
    assert len(levels) == 2 * ENVELOPE_HZ
    assert all(0.0 <= v <= 1.0 for v in levels)
    assert max(levels) == pytest.approx(1.0)
    # The tone swells to its loudest in the middle, so the middle is louder than the start.
    assert levels[len(levels) // 2] > levels[0]


def test_wav_envelope_is_zero_for_silence(tmp_path):
    path = tmp_path / 'silence.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 800)
    assert wav_envelope(str(path)) == [0.0] * 3  # 0.1 s of silence at 30 values a second, rounded up


@pytest.mark.parametrize('bad', [None, '', 'missing.wav', 12])
def test_wav_envelope_returns_empty_list_for_a_missing_or_bad_path(bad):
    assert wav_envelope(bad) == []


def test_wav_envelope_returns_empty_list_for_a_file_that_is_not_a_wav(tmp_path):
    path = tmp_path / 'not-a-wav.wav'
    path.write_bytes(b'this is an mp3-ish blob, not PCM')
    assert wav_envelope(str(path)) == []


def test_wav_envelope_returns_empty_list_for_an_unsupported_sample_width(tmp_path):
    path = tmp_path / 'wide.wav'
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(3)
        wav.setframerate(8000)
        wav.writeframes(b'\x01\x02\x03' * 800)
    assert wav_envelope(str(path)) == []


def test_wav_envelope_for_a_longer_file_scales_with_its_length(tmp_path):
    path = _write_wav(tmp_path / 'long.wav', seconds=5.0, width=2, channels=2)
    assert len(wav_envelope(str(path))) == 5 * ENVELOPE_HZ


# ---- import hygiene --------------------------------------------------------------------------------------

def test_voice_state_modules_import_with_no_appkit_or_quartz(monkeypatch):
    for name in ('AppKit', 'Quartz', 'objc', 'Foundation'):
        monkeypatch.setitem(sys.modules, name, None)
    for module_name in ('orb_character', 'orb_motion'):
        sys.modules.pop(module_name, None)
        __import__(module_name)
