"""Character rules for the orb: eye shapes, idle accents, breath timing, and the voice state machine. Pure Python.

Every random choice takes an injected random.Random, so tests can seed it. No AppKit, Quartz or Cocoa.
orb_state lives here (orb_view re-exports it) so resolve() can build on it without an import cycle.
"""
import math
import re
from collections import namedtuple

from orb_motion import (
    ROUGH_REVERSALS,
    ROUGH_SECONDS,
    BREATH_FRAMES,
    BREATH_SCALE_X,
    BREATH_SCALE_Y,
    CLIP_FPS,
    sample_track,
    spring_decay,
)

# Handle length for a cubic through four cardinal points. 0.2762 is kappa / 2, so the open eye is a true circle.
HANDLE = 0.2762
EYE_POINTS = 13  # one move, then four cubic segments (three points each), per eye shape

# Four anchors per shape (top, right, bottom, left) as fractions of the eye size. Every point stays in 0..1.
# Restored from 1c63b74: the eyes are cream bars, 4 pt wide (0.318..0.682 of 11 pt) and 10 pt tall, so the
# open shape is a stadium and the closed shapes are flat bars. Blink and thinking still morph between them.
EYE_SHAPES = {
    "open": ((0.5, 0.045), (0.682, 0.5), (0.5, 0.955), (0.318, 0.5)),
    "closedDown": ((0.5, 0.5), (0.682, 0.56), (0.5, 0.62), (0.318, 0.56)),
    "closedUp": ((0.5, 0.36), (0.682, 0.44), (0.5, 0.5), (0.318, 0.44)),
    "smileClosed": ((0.5, 0.28), (0.682, 0.62), (0.5, 0.5), (0.318, 0.62)),
    # PR 7: wide is the same 4 pt bar, run the full 11 pt height, so listening reads as taller eyes, not a diamond.
    "wide": ((0.5, 0.0), (0.73, 0.5), (0.5, 1.0), (0.27, 0.5)),
    # PR 7: a sceptic eye is one shorter bar, tilted, so it reads as a raised eyebrow. Same four anchors.
    "sceptic": ((0.6, 0.27), (0.68, 0.5), (0.4, 0.73), (0.32, 0.5)),
    # PR 8: a squinted pill, short and a little wide, for thinking.
    "squint": ((0.5, 0.22), (0.66, 0.5), (0.5, 0.78), (0.34, 0.5)),
    # PR 7b: reaction emotions, all original pill-based loops with the same 4 anchors.
    "happy": ((0.5, 0.44), (0.68, 0.6), (0.5, 0.68), (0.32, 0.6)),  # a short, low, smiling bar
    "sad": ((0.66, 0.3), (0.7, 0.55), (0.5, 0.8), (0.3, 0.55)),  # drooping, leaning in
    "heart": ((0.5, 0.92), (0.74, 0.5), (0.5, 0.1), (0.26, 0.5)),  # a rounded lozenge, read as a heart at speed
    "spiral": ((0.62, 0.0), (0.7, 0.5), (0.38, 1.0), (0.3, 0.5)),  # a tilted full-height bar; the wobble makes it spin
}

# lookIntensity by character state. Only "idle" is driven by PR 2; the other rows are the plan's table for later PRs.
STATE_LOOK = {"idle": 1.0, "listening": 0.6, "thinking": 0.0, "searching": 0.3, "speaking": 0.5, "still": 0.0}

Accent = namedtuple("Accent", "name frames weight look")

# The idle accents from the plan's Character model table. Frames are at CLIP_FPS.
ACCENTS = (
    Accent("blink", 20, 30, 1.0),
    Accent("blink_stagger", 28, 15, 1.0),
    Accent("double_blink", 42, 10, 1.0),
    Accent("look_around", 90, 12, 0.0),
    Accent("yawn", 96, 6, 0.0),
    Accent("bounce", 36, 8, 0.5),
    Accent("jiggle", 30, 4, 1.0),
    Accent("happy", 60, 8, 0.0),
    Accent("wave", 72, 5, 0.5),  # PR 7b: a small original hand nub sways at the body's upper right
    Accent("balance_eyes", 84, 2, 0.2),  # PR 7b: the body tilts left, then right, +-4 degrees (pupils are gone)
)
_ACCENT_BY_NAME = {accent.name: accent for accent in ACCENTS}


def eye_shape(name, size):
    """Closed Bézier loop for an eye, as 13 (x, y) points in the eye's own coordinates."""
    try:
        anchors = EYE_SHAPES[name]
    except KeyError:
        raise ValueError("unknown eye shape: %r" % (name,))
    points = [(x * size, y * size) for x, y in anchors]
    count = len(points)
    out = [points[0]]
    for i in range(count):
        p0 = points[(i - 1) % count]
        p1 = points[i]
        p2 = points[(i + 1) % count]
        p3 = points[(i + 2) % count]
        out.append((p1[0] + HANDLE * (p2[0] - p0[0]), p1[1] + HANDLE * (p2[1] - p0[1])))
        out.append((p2[0] - HANDLE * (p3[0] - p1[0]), p2[1] - HANDLE * (p3[1] - p1[1])))
        out.append(p2)
    return tuple(out)


def accent_seconds(name):
    return _ACCENT_BY_NAME[name].frames / float(CLIP_FPS)


def _frames(count):
    return count / float(CLIP_FPS)


def _blink(start):
    """Open, closed (half-way through 20 frames), open. Used by every blink accent."""
    return [(start, "open"), (start + _frames(10), "closedDown"), (start + _frames(20), "open")]


def _hop(t):
    """A 6 pt hop that lands at 0.36 s."""
    if t >= 0.36:
        return 0.0
    u = t / 0.36
    return 6.0 * 4.0 * u * (1.0 - u)


def _landing_squash(t):
    """Scale y dips 6% on landing, then the spring (k=500, c=18) settles it back to 1."""
    if t < 0.36:
        return 1.0
    return 1.0 - 0.06 * spring_decay(500.0, 18.0, t - 0.36)


def _jiggle(t):
    return 1.0 + 0.04 * spring_decay(500.0, 14.0, t)


def _tl_blink():
    return {"eyes_L": _blink(0.0), "eyes_R": _blink(0.0)}


def _tl_blink_stagger():
    left = _blink(0.0) + [(_frames(28), "open")]
    right = _blink(_frames(5)) + [(_frames(28), "open")]  # the right eye follows about 0.08 s later
    return {"eyes_L": left, "eyes_R": right}


def _tl_double_blink():
    return {"eyes_L": _blink(0.0) + _blink(_frames(22)), "eyes_R": _blink(0.0) + _blink(_frames(22))}


def _tl_look_around():
    return {"pupil_x": [(0.0, 0.0), (0.4, -2.2), (0.9, 2.2), (1.5, 0.0)]}


def _tl_yawn():
    eyes = [(0.0, "open"), (0.4, "closedUp"), (1.2, "closedUp"), (1.6, "open")]
    mouth = [(0.0, 0.0), (0.4, 1.0), (1.2, 1.0), (1.6, 0.0)]
    body = [(0.0, 1.0), (0.5, 1.06), (1.1, 1.06), (1.6, 1.0)]
    return {"eyes_L": eyes, "eyes_R": list(eyes), "mouth": mouth, "body_sy": body}


def _tl_bounce():
    return {"body_y": sample_track(_hop, 0.6), "body_sy": sample_track(_landing_squash, 0.6)}


def _tl_jiggle():
    return {"body_scale": sample_track(_jiggle, 0.5)}


def _tl_happy():
    eyes = [(0.0, "open"), (0.25, "smileClosed"), (0.75, "smileClosed"), (1.0, "open")]
    return {"eyes_L": eyes, "eyes_R": list(eyes)}


def _tl_wave():
    """Nub sway: +-20 degrees on a 0.2 s period, shown for the whole accent."""
    sway = sample_track(lambda t: 20.0 * math.sin(math.tau * t / 0.2), 1.2)
    return {"nub_rot": sway, "nub_opacity": [(0.0, 0.0), (0.05, 1.0), (1.12, 1.0), (1.2, 0.0)]}


def _tl_balance_eyes():
    """One tilt cycle: left, then right, +-4 degrees about the body centre."""
    return {"body_rot": sample_track(lambda t: 4.0 * math.sin(math.tau * t / 1.4), 1.4)}


_TIMELINES = {
    "blink": _tl_blink,
    "blink_stagger": _tl_blink_stagger,
    "double_blink": _tl_double_blink,
    "look_around": _tl_look_around,
    "yawn": _tl_yawn,
    "bounce": _tl_bounce,
    "jiggle": _tl_jiggle,
    "happy": _tl_happy,
    "wave": _tl_wave,
    "balance_eyes": _tl_balance_eyes,
}


def accent_timeline(name):
    """Channel -> [(t, value)] for one accent. Eye channels hold shape names. Every track ends at accent_seconds."""
    return _TIMELINES[name]()


def next_accent_delay(rng):
    return rng.uniform(4.0, 9.0)


def pick_accent(rng, previous=None):
    """Weighted pick that never returns the previous accent."""
    choices = [accent for accent in ACCENTS if accent.name != previous]
    return rng.choices([accent.name for accent in choices], weights=[accent.weight for accent in choices])[0]


def breath_speed(rng):
    return rng.uniform(0.5, 1.3)


def breath_timeline(cycles):
    """[(t, scale_x, scale_y)] for back-to-back breath cycles, one cycle per entry in seconds."""
    out = [(0.0, 1.0, 1.0)]
    t = 0.0
    for cycle in cycles:
        out.append((t + cycle / 2.0, BREATH_SCALE_X, BREATH_SCALE_Y))
        t += cycle
        out.append((t, 1.0, 1.0))
    return out


def breath_batch(rng, count=8):
    """A batch of breath cycles, each 7.5 s divided by its own random speed."""
    base = BREATH_FRAMES / float(CLIP_FPS)
    return breath_timeline([base / breath_speed(rng) for _ in range(count)])


def look_intensity(state, clip=None):
    """How much the pupils follow the cursor. A clip overrides its state's value."""
    if clip is not None and clip in _ACCENT_BY_NAME:
        return _ACCENT_BY_NAME[clip].look
    return STATE_LOOK.get(state, 1.0)


# PR 7: voice states. orb_state maps Jev's status text to a coarse state; resolve() turns that into the character state.

def orb_state(status, held=False):
    if held or status in ("Listening", "Dictating"):
        return "listening"
    if status in ("Transcribing", "Thinking", "Doing it", "Finishing"):
        return "thinking"
    if status == "Speaking":
        return "speaking"
    if status in ("Something went wrong", "Time's up"):
        return "error"
    return "idle"


def resolve(status, held, reduce_motion, menu_open):
    """The character state for the orb. One of idle, listening, thinking, searching, speaking or still.

    Reduce Motion (and screens asleep, which the caller folds into reduce_motion) gives still. Errors also hold
    still, as they did before PR 7, because the failure reaction is PR 7b. "Doing it" is searching. menu_open does
    not change the state: it only suspends idle accents, which orb_view already gates on the popover flag.
    """
    if reduce_motion:
        return "still"
    base = orb_state(status, held)
    if base == "error":
        return "still"
    if base == "thinking" and status == "Doing it" and not held:
        return "searching"
    if base in ("listening", "thinking", "speaking"):
        return base
    return "idle"


# A clip sets the eye shapes (left, right), the eye height, pupil bias, body lean, the spinner, the scan
# amplitude in points (searching only) and whether the eyes squint on speech peaks.
Clip = namedtuple("Clip", "eyes scale_y bias lean spinner sweep squint")

CLIPS = {
    "listen_1": Clip(("wide", "wide"), 1.15, (0.0, 0.0), 0.0, False, 0.0, False),
    "listen_2": Clip(("wide", "wide"), 1.10, (0.4, 0.0), -2.0, False, 0.0, False),
    "listen_3": Clip(("wide", "wide"), 1.20, (-0.4, 0.0), 2.0, False, 0.0, False),
    "think_1": Clip(("squint", "squint"), 1.0, (1.8, 1.8), 0.0, True, 0.0, False),
    "think_2": Clip(("sceptic", "open"), 1.0, (0.8, 1.0), 0.0, True, 0.0, False),
    "think_3": Clip(("open", "open"), 1.0, (0.0, 2.2), 0.0, True, 0.0, False),
    "search_1": Clip(("open", "open"), 1.0, (0.0, 0.0), 0.0, True, 2.0, False),
    "search_2": Clip(("open", "open"), 1.0, (0.0, 0.0), 0.0, True, 1.2, False),
    "talk_1": Clip(("open", "open"), 1.0, (0.0, 0.0), 0.0, False, 0.0, True),
    "talk_2": Clip(("open", "open"), 1.0, (0.0, 0.0), 1.0, False, 0.0, True),
    "talk_3": Clip(("open", "open"), 0.97, (0.0, 0.0), -1.0, False, 0.0, True),
    "talk_4": Clip(("open", "open"), 1.0, (0.0, 0.0), 0.5, False, 0.0, True),
}

STATE_CLIPS = {
    "idle": (),  # idle uses the PR 2 accents, not clips
    "listening": ("listen_1", "listen_2", "listen_3"),
    "thinking": ("think_1", "think_2", "think_3"),
    "searching": ("search_1", "search_2"),
    "speaking": ("talk_1", "talk_2", "talk_3", "talk_4"),
    "still": (),
}

LOOK_EASE_SECONDS = 0.25  # lookIntensity eases between states over this long
SWITCH_SECONDS = {"thinking": 7.0, "searching": 4.0, "listening": 3.0}


def next_clip(state, rng, previous=None):
    """A clip for the state that is never the previous one. None for states without clips."""
    names = STATE_CLIPS.get(state, ())
    if not names:
        return None
    choices = [name for name in names if name != previous] or list(names)
    return rng.choice(choices)


def clip_switch_delay(state, rng):
    """Seconds until the state's next clip. None when the state has no clip cycle."""
    if state == "speaking":
        return rng.uniform(2.0, 4.0)
    return SWITCH_SECONDS.get(state)


def ease_look(start, target, elapsed, duration=LOOK_EASE_SECONDS):
    """lookIntensity on its way from start to target: smoothstep over duration seconds, and finite for bad input."""
    try:
        a, b, t = float(start), float(target), float(elapsed)
    except (TypeError, ValueError):
        return 0.0
    if not all(math.isfinite(v) for v in (a, b, t)):
        return b if math.isfinite(b) else 0.0
    if duration <= 0.0 or t >= duration:
        return b
    if t <= 0.0:
        return a
    u = t / duration
    return a + (b - a) * (u * u * (3.0 - 2.0 * u))


# PR 7b: one-shot reactions. The table, the queue with cooldowns, and the trigger rules. Pure Python.

Reaction = namedtuple("Reaction", "name seconds priority cooldown eyes body glyph")

# name: (seconds, priority, cooldown seconds, eye keyframes [(t, shape)] for both eyes, body channel and amount, glyph).
# Priorities and cooldowns are the plan's table. wave is once per launch: an infinite cooldown on this queue.
REACTIONS = {
    "get_ready": Reaction("get_ready", 0.35, 3, 0.0, ((0.0, "wide"),), ("hop", 4.0), False),
    "success": Reaction("success", 0.8, 2, 20.0, ((0.0, "smileClosed"),), ("spin_hop", 6.0), False),
    "failure": Reaction("failure", 1.0, 3, 5.0, ((0.0, "sad"), (0.5, "sceptic")), ("droop", 0.06), False),
    "dizzy": Reaction("dizzy", 1.2, 2, 10.0, ((0.0, "spiral"),), ("wobble", 6.0), False),
    "heart": Reaction("heart", 1.0, 1, 60.0, ((0.0, "heart"),), ("pulse", 0.08), False),
    "low_disk": Reaction("low_disk", 1.5, 1, 3600.0, ((0.0, "sad"),), ("none", 0.0), True),
    "wave": Reaction("wave", 1.2, 1, float("inf"), ((0.0, "open"),), ("none", 0.0), False),
}

LOW_DISK_BYTES = 10 * 1024 ** 3  # 10 GB
LOW_DISK_FRACTION = 0.05


def reaction_body_tracks(name):
    """Body channels for a reaction, sampled at CLIP_FPS: {"y": [(t, pt)], "rot": [(t, deg)], "sy": [(t, k)], "scale": [(t, k)]}.

    Only the channels the reaction uses are present. Values are relative to rest, so 0 means no change.
    """
    reaction = REACTIONS[name]
    channel, amount = reaction.body
    seconds = reaction.seconds
    tracks = {}
    if channel == "hop":
        tracks["y"] = sample_track(lambda t: amount * 4.0 * (t / seconds) * (1.0 - t / seconds), seconds)
    elif channel == "spin_hop":
        tracks["y"] = sample_track(lambda t: amount * 4.0 * (t / seconds) * (1.0 - t / seconds), seconds)
        tracks["rot"] = sample_track(lambda t: 360.0 * (t / seconds), seconds)
    elif channel == "droop":
        tracks["sy"] = sample_track(lambda t: 1.0 - amount * math.sin(math.pi * t / seconds), seconds)
    elif channel == "wobble":
        tracks["rot"] = sample_track(
            lambda t: amount * math.sin(math.tau * 2.0 * t / seconds) * (1.0 - t / seconds), seconds)
    elif channel == "pulse":
        tracks["scale"] = sample_track(lambda t: 1.0 + amount * math.sin(math.pi * t / seconds), seconds)
    return tracks


def is_thanks(text):
    """True for a turn that thanks Jev: "thanks", "thank you", "love you Jev". False for "no thanks" and for empty text.

    Matching is on whole words, so punctuation and case do not matter.
    """
    words = " ".join(re.sub(r"[^a-z]+", " ", str(text or "").lower()).split())
    if not words:
        return False
    if re.search(r"\bno thanks\b", words):
        return False
    return bool(re.search(r"\bthanks\b|\bthank you\b|\blove you jev\b", words))


def rough_drag(peak_window, seconds_fast):
    """A drop after a rough drag: ROUGH_REVERSALS reversals inside any ROUGH_WINDOW_SECONDS, or ROUGH_SECONDS above ROUGH_SPEED.

    peak_window is Roughness.peak_window (the most reversals in any window), seconds_fast is Roughness.seconds_fast.
    """
    try:
        return int(peak_window) >= ROUGH_REVERSALS or float(seconds_fast) >= ROUGH_SECONDS
    except (TypeError, ValueError):
        return False


def low_disk(free_bytes, total_bytes):
    """True when free space is under 10 GB or under 5% of the disk. Bad input is not low."""
    try:
        free, total = float(free_bytes), float(total_bytes)
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(free) and math.isfinite(total)) or total <= 0.0:
        return False
    return free < LOW_DISK_BYTES or free / total < LOW_DISK_FRACTION


def disk_check(usage=None, path="/"):
    """True when the disk at path is low. usage defaults to shutil.disk_usage; tests pass a fake, so the real disk is never read."""
    import shutil
    usage = usage or shutil.disk_usage
    try:
        result = usage(path)
        return low_disk(result.free, result.total)
    except OSError:
        return False


_IDLE_LINES = ("Ready when you are", "Didn't catch", "Say “Hey Jev”")


def is_real_reply(detail):
    """A status detail that is an answer, not an idle or error line. Empty text and the idle lines are not replies."""
    text = str(detail or "").strip()
    if not text:
        return False
    return not any(text.startswith(line) for line in _IDLE_LINES)


_BUSY = {"Doing it", "Thinking", "Transcribing", "Finishing", "Speaking"}


def reaction_for_status(previous, state, detail):
    """The reaction a status change calls for, or None.

    success: a command ended on Ready with a real reply, after a busy state. failure: an error or Time's up.
    """
    if state in ("Something went wrong", "Time's up"):
        return "failure"
    if state == "Ready" and previous in _BUSY and is_real_reply(detail):
        return "success"
    return None


class ReactionQueue:
    """One reaction plays at a time. Cooldowns hold per reaction. Clock is injected, so tests use a fake clock."""

    def __init__(self, clock):
        self._clock = clock
        self._current = None  # (name, start, end)
        self._last = {}  # name -> when it last started

    def offer(self, name, now=None):
        """Start a reaction if its cooldown has passed and no higher-priority one is playing. True if it started.

        An equal or higher priority replaces a reaction that is playing. A lower one waits for the next offer.
        """
        if name not in REACTIONS:
            raise ValueError("unknown reaction: %r" % (name,))
        now = float(self._clock() if now is None else now)
        spec = REACTIONS[name]
        last = self._last.get(name)
        if last is not None and now - last < spec.cooldown:
            return False
        playing = self.current(now)
        if playing is not None and REACTIONS[playing].priority > spec.priority:
            return False
        self._current = (name, now, now + spec.seconds)
        self._last[name] = now
        return True

    def current(self, now=None):
        """The reaction playing now, or None once its duration has passed."""
        now = float(self._clock() if now is None else now)
        if self._current is None:
            return None
        name, _start, end = self._current
        if now >= end:
            self._current = None
            return None
        return name

    def cancel_all(self):
        """Stop the reaction that is playing. Cooldowns are kept, so it cannot replay at once."""
        self._current = None
