"""Original orb rules; no Cocoa, microphone, services or credentials."""
import math
import pytest
from mini_bar import expanded_frame_from_capsule
from orb_view import OrbTicker, orb_frame, orb_pose, orb_state


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


def test_idle_breath_blink_thinking_sweep_and_audio_bounds():
    assert orb_pose('idle', 1)[0] == 1.5
    assert orb_pose('idle', 6.9)[1] < orb_pose('idle', 0)[1]
    assert orb_pose('thinking', 0.75)[2] == 8
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
