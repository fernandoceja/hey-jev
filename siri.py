"""Mac voice assistant: hold right Option or say "Hey Jev", then speak. Jev decides, Fish speaks."""
import os, re, sys, json, time, queue, random, argparse, subprocess, tempfile, threading, hashlib, collections
from datetime import datetime
import numpy as np, requests, sounddevice as sd, soundfile as sf
from dotenv import load_dotenv
from pynput import keyboard
import commands
from secrets_store import get_secret

load_dotenv()
TS_KEY = get_secret("TYPESAFE_API_KEY")
FISH_KEY = get_secret("FISH_AUDIO_API_KEY")
OR_KEY = get_secret("OPENROUTER_API_KEY")
VOICE_ID = "9a9cf47702da476aa4629e2506d4a857"
PTT_KEY = keyboard.Key.alt_r
SAMPLE_RATE = 16000
GATE = 0.65
WHISPER_MODEL = "small.en"
COMMAND_PROMPT = (
    "Open Spotify. Open CapCut. Open ChatGPT. Open Cursor. Open Claude. Quit Safari. "
    "What time is it. What's the date. What's my schedule today. When's my next shift. What's next. "
    "What apps are open. Run shortcut Leaving for work. Set a timer for five minutes. "
    "Play. Pause. Next track. Turn Spotify down. Turn the Mac volume down. Mute. Dark mode on. Lock the screen."
)
WAKE_PROMPT = (
    "Hey Jev, open CapCut. Hey Jev, open ChatGPT. Hey Jev, what time is it. "
    "Hey Jev, what's my schedule today. Hey Jev, pause the music."
)
# Whisper often hears "Jev" as Jeff or Jeb, so accept the close ones
WAKE = re.compile(r"^\W*(?:hey|hi|hay|okay|ok|a)\W+(?:jev|jevs|jeff|jeffs|jef|jeb|jab|chev|jeve|jav)\b\W*", re.I)
WAKE_WINDOW = 6.0


def reload_keys():
    global TS_KEY, FISH_KEY, OR_KEY
    TS_KEY = get_secret("TYPESAFE_API_KEY")
    FISH_KEY = get_secret("FISH_AUDIO_API_KEY")
    OR_KEY = get_secret("OPENROUTER_API_KEY")

# --------------------------------------------------------------------------- Jev
QUESTIONS = {
    "category": {"type": "choice", "instructions": "What kind of request is this?",
                 "criteria": {"mac_command": "asks the computer to do something",
                              "information_request": "asks a general knowledge or factual question",
                              "chit_chat": "just talking, greeting, or thanking",
                              "unclear": "garbled, empty, or makes no sense"}},
    "compound": {"type": "noul", "instructions": "Does the request contain more than one distinct action?"},
    "target": {"type": "choice", "instructions": "What is the primary thing being controlled?",
               "criteria": {"app": "an application", "volume": "sound level", "display": "screen appearance or dark mode",
                            "media": "music playback", "system": "locking or sleeping the computer",
                            "timer": "setting, checking, or cancelling a timer or reminder",
                            "info": "the time, the date, the calendar, a shift, or which apps are open",
                            "shortcut": "running a named Apple Shortcut"}},
    "app": {"type": "choice", "instructions": "Which app, if any, is named?",
            "criteria": {"spotify": None, "slack": None, "chrome": None, "vscode": None, "finder": None,
                         "safari": None, "messages": None, "notes": None, "cursor": None, "claude": None,
                         "chatgpt": None, "capcut": None,
                         "other": "an application is named that is not one of the apps listed above",
                         "none": "no specific application is named"}},
    "app_action": {"type": "choice", "instructions": "What should happen to the app?",
                   "criteria": {"open": "open, launch, or start the app itself", "quit": "quit, close, or kill the app",
                                "none": "the request is about playback, volume, or something inside the app, not opening or quitting it"}},
    "volume_action": {"type": "choice", "instructions": "What should happen to the volume, if anything?",
                      "criteria": {"up": None, "down": None, "mute": None, "unmute": None,
                                   "set": "set to a specific level", "none": None}},
    "volume_scope": {"type": "choice", "instructions": "Which volume should change?",
                     "criteria": {"spotify": "Spotify's own in-app volume when Spotify is explicitly named",
                                  "system": "the Mac's overall output volume, including unqualified volume requests"}},
    "volume_level": {"type": "score", "instructions": "If a volume level is asked for, how loud?",
                     "criteria": ["silent", "quiet", "medium", "loud", "max"]},
    "display_action": {"type": "choice", "instructions": "What should happen to dark mode?",
                       "criteria": {"dark_on": None, "dark_off": None, "toggle": None, "none": None}},
    "media_action": {"type": "choice", "instructions": "What should happen to music playback?",
                     "criteria": {"play": None, "pause": None, "next": None, "previous": None, "none": None}},
    "timer_action": {"type": "choice", "instructions": "What should happen with a timer or reminder?",
                     "criteria": {"set": "start a timer or set a reminder", "check": "ask how much time is left",
                                  "cancel": "stop or cancel a timer", "none": None}},
    "system_action": {"type": "choice", "instructions": "What should happen to the computer?",
                      "criteria": {"lock": None, "sleep": None, "none": None}},
    "info_action": {"type": "choice", "instructions": "What local information is being asked for?",
                    "criteria": {"time": "the current time",
                                 "date": "today's date or the day of the week",
                                 "next_event": "the next calendar event, including 'what's next'",
                                 "today_schedule": "the calendar schedule for today",
                                 "next_shift": "the next work shift, including R345 or Apple",
                                 "open_apps": "which applications are currently open",
                                 "none": None}},
    "shortcut_action": {"type": "choice", "instructions": "What should happen with a Shortcut?",
                        "criteria": {"run": "run, start, or do a named Shortcut", "none": None}},
}


def split_questions():
    """The same branch questions twice, one set scoped to the first action asked for, one to the second."""
    out = {}
    for slot, word in (("first", "FIRST"), ("second", "SECOND")):
        for k, q in QUESTIONS.items():
            if k in ("category", "compound"):
                continue
            out[f"{slot}_{k}"] = {**q, "instructions": f"Considering ONLY the {word} action the user asks for: {q['instructions']}"}
    return out


SPLIT_QUESTIONS = split_questions()


def jev(text, questions=None):
    t = time.time()
    r = requests.post("https://api.typesafe.ai/v1/systemone", json={"model": "jev-latest", "state": text, "questions": questions or QUESTIONS},
                      headers={"Authorization": f"Bearer {TS_KEY}"}, timeout=30)
    r.raise_for_status()
    j = r.json()
    ans = {}
    for k, a in j["answers"].items():
        if a["type"] == "noul":  # probability, confidence is distance from 0.5
            ans[k] = (a["noul"] >= 0.5, max(a["noul"], 1 - a["noul"]))
        elif a["type"] == "score":  # index into the rubric, legend maps it back to the label
            ans[k] = (a["legend"][str(int(round(a["score"])))], a.get("confidence", 0))
        else:
            ans[k] = (a["choice"], a.get("confidence", 0))
    cost = j.get("usage", {}).get("input_tokens", 0) * 0.042 / 1e6 
    return ans, int((time.time() - t) * 1000), cost


# --------------------------------------------------------------------------- Mac actions
# Favourites only. warm_cache pre-renders {app} for these names, not for every app on disk.
APPS = {"spotify": "Spotify", "slack": "Slack", "chrome": "Google Chrome", "vscode": "Visual Studio Code",
        "finder": "Finder", "safari": "Safari", "messages": "Messages", "notes": "Notes",
        "cursor": "Cursor", "claude": "Claude", "chatgpt": "ChatGPT", "capcut": "CapCut"}
LEVELS = {"silent": 0, "quiet": 25, "medium": 50, "loud": 75, "max": 100}


def osa(script):
    """Fixed AppleScript only. Spoken text must go through osa_args(), never an f-string."""
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "AppleScript failed")
    return result.stdout.strip()


def osa_args(script, *args):
    """Run AppleScript that reads spoken text from argv.

    The script starts with `on run argv` and uses `item 1 of argv`, `item 2 of argv`, and so on.
    User-controlled strings are passed as separate arguments so they are not interpolated.
    """
    result = subprocess.run(["osascript", "-e", script, *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "AppleScript failed")
    return result.stdout.strip()


def sh(*cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {' '.join(cmd)}")


def volume():
    return int(osa("output volume of (get volume settings)"))


def spotify_volume():
    return int(osa('tell application "Spotify" to get sound volume'))


def spotify_play(tries=12):
    """Spotify ignores play while it's still loading, so keep asking until it says it's playing."""
    for _ in range(tries):
        osa('tell application "Spotify" to play')
        time.sleep(0.5)
        if osa('tell application "Spotify" to player state') == "playing":
            return
    raise RuntimeError("Spotify never started playing")


def _quiet(fn):
    """Side effect only. osascript's stdout is not a sentence; REPLIES supplies that."""
    def run(arg, text):
        fn(arg, text)
    return run


ACTIONS = {
    "app_open": lambda arg, text: commands.open_any_app(arg, text, APPS),
    "app_quit": lambda arg, text: commands.quit_any_app(arg, text, APPS),
    "apps_quit_all": lambda _arg, text: commands.quit_all_apps(),
    "volume_up": _quiet(lambda _arg, _text: osa(f"set volume output volume {min(100, volume() + 20)}")),
    "volume_down": _quiet(lambda _arg, _text: osa(f"set volume output volume {max(0, volume() - 20)}")),
    "volume_mute": _quiet(lambda _arg, _text: osa("set volume output muted true")),
    "volume_unmute": _quiet(lambda _arg, _text: osa("set volume output muted false")),
    "volume_set": _quiet(lambda lvl, _text: osa(f"set volume output volume {LEVELS.get(lvl, 50)}")),
    "spotify_volume_up": _quiet(lambda _arg, _text: osa(f'tell application "Spotify" to set sound volume to {min(100, spotify_volume() + 20)}')),
    "spotify_volume_down": _quiet(lambda _arg, _text: osa(f'tell application "Spotify" to set sound volume to {max(0, spotify_volume() - 20)}')),
    "spotify_volume_mute": _quiet(lambda _arg, _text: osa('tell application "Spotify" to set sound volume to 0')),
    "spotify_volume_unmute": _quiet(lambda _arg, _text: osa('tell application "Spotify" to set sound volume to 50')),
    "spotify_volume_set": _quiet(lambda lvl, _text: osa(f'tell application "Spotify" to set sound volume to {LEVELS.get(lvl, 50)}')),
    "display_dark_on": _quiet(lambda _arg, _text: osa('tell application "System Events" to tell appearance preferences to set dark mode to true')),
    "display_dark_off": _quiet(lambda _arg, _text: osa('tell application "System Events" to tell appearance preferences to set dark mode to false')),
    "display_toggle": _quiet(lambda _arg, _text: osa('tell application "System Events" to tell appearance preferences to set dark mode to not dark mode')),
    "media_play": _quiet(lambda _arg, _text: spotify_play()),
    "media_pause": _quiet(lambda _arg, _text: osa('tell application "Spotify" to pause')),
    "media_next": _quiet(lambda _arg, _text: osa('tell application "Spotify" to next track')),
    "media_previous": _quiet(lambda _arg, _text: osa('tell application "Spotify" to previous track')),
    "system_lock": _quiet(lambda _arg, _text: osa('tell application "System Events" to keystroke "q" using {control down, command down}')),
    "system_sleep": _quiet(lambda _arg, _text: sh("pmset", "sleepnow")),
    "info_time": lambda _arg, _text: commands.speak_time(),
    "info_date": lambda _arg, _text: commands.speak_date(),
    "info_next_event": lambda _arg, _text: commands.speak_next_event(),
    "info_today_schedule": lambda _arg, _text: commands.speak_today_schedule(),
    "info_next_shift": lambda _arg, _text: commands.speak_next_shift(),
    "info_open_apps": lambda _arg, _text: commands.speak_open_apps(),
    "shortcut_run": lambda _arg, text: commands.run_named_shortcut(text),
}

# --------------------------------------------------------------------------- Scripted replies with Fish tags
REPLIES = {
    "app_open": ["[cheerful] {app}'s up.", "{app}, opening now.", "[chuckling] There you go, {app}."],
    "app_quit": ["{app}'s gone.", "[sighing] Closing {app}. Good riddance.", "Done, {app} is closed."],
    "volume_up": ["Louder it is.", "[cheerful] Turning it up.", "Up we go."],
    "volume_down": ["Bringing it down.", "[sighing] A little quieter.", "Turning it down."],
    "volume_mute": ["[sighing] Muting. Finally some quiet.", "Muted.", "Shh. Muted."],
    "volume_unmute": ["Sound's back.", "[cheerful] Unmuted.", "And we're back."],
    "volume_set": ["Set to {level}.", "Volume's {level} now."],
    "spotify_volume_up": ["Turning Spotify up.", "[cheerful] Spotify's louder."],
    "spotify_volume_down": ["Turning Spotify down.", "Spotify's a little quieter."],
    "spotify_volume_mute": ["Spotify's muted.", "[sighing] Muting Spotify."],
    "spotify_volume_unmute": ["Spotify's sound is back.", "[cheerful] Spotify's unmuted."],
    "spotify_volume_set": ["Spotify's set to {level}.", "Set Spotify to {level}."],
    "display_dark_on": ["[chuckling] Lights off.", "Dark mode on.", "Going dark."],
    "display_dark_off": ["[cheerful] Let there be light.", "Dark mode off.", "Back to light."],
    "display_toggle": ["Flipped it.", "There, switched."],
    "media_play": ["[cheerful] Playing.", "Music's on.", "Here we go."],
    "media_pause": ["Paused.", "[sighing] Pausing. Take your time.", "Holding it there."],
    "media_next": ["Skipping.", "[chuckling] Not a fan? Next one.", "Next track."],
    "media_previous": ["Going back one.", "Previous track.", "[chuckling] Again? Sure."],
    "system_lock": ["Locking up. See you soon.", "Locked.", "Screen's locked."],
    "system_sleep": ["Good night.", "Sleeping now.", "[sighing] Finally, a nap."],
    "info": ["[chuckling] That's a question, not a command. I'll get a brain for that soon.",
             "[sighing] I can't answer that one yet."],
    "chit_chat": ["[chuckling] Hi. Give me something to do.", "[cheerful] Hey. I'm listening."],
    "compound_done": ["[chuckling] Done, both of them.", "[cheerful] All done.", "Both sorted."],
    "wake": ["Yes?", "[cheerful] Mm-hm?", "I'm listening."],
    "clarify": ["[clear throat] Sorry, say that again?", "Hm, one more time?"],
    "give_up": ["[sighing] I'm not sure what you mean. Try saying it differently?"],
    "timer_set": ["[cheerful] Timer's set.", "On it. I'll let you know.", "Done, counting down."],
    "reminder_set": ["Got it, I'll remind you.", "[cheerful] Sure, I'll give you a shout."],
    "timer_check": ["{left} left.", "You've got {left} to go."],
    "timer_cancel": ["Timer cancelled.", "[sighing] Fine, no timer then."],
    "timers_cancel": ["All timers cancelled.", "Cleared them all."],
    "timer_none": ["[chuckling] There's no timer running."],
    "timer_unclear": ["[clear throat] How long for?"],
    "timer_done": ["[cheerful] Time's up!", "[chuckling] Ding ding, time's up."],
    "reminder_done": ["[cheerful] Hey, just a reminder: {label}.", "Reminder: {label}."],
    "unsupported": ["[chuckling] I know what you want, I just can't do that one yet."],
    "apps_quit_all": ["Quit every app except Finder and Hey Jev? Say yes to quit them."],
    "confirm_no": ["Okay, I won't.", "Cancelled."],
    "quit_all_alone": ["Quit all has to be on its own. Say it by itself, then yes to confirm."],
}


TARGETS = ("app", "volume", "display", "media", "system", "timer", "info", "shortcut")
SPEAK_FIRST = {"volume_mute", "system_lock", "system_sleep"}


def say_line(key, **fmt):
    return random.choice(REPLIES[key]).format(**fmt)


# --------------------------------------------------------------------------- Timers and reminders
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
                "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
                "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "ninety": 90, "couple": 2, "few": 3}
UNITS = {"s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1, "m": 60, "min": 60, "mins": 60,
         "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600}
DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b(\s+and\s+a\s+half)?")


def _digits(text):
    """'twenty five minutes' -> '25 minutes', 'half an hour' -> '30 minutes'."""
    t = re.sub(r"\bhalf an? hour\b", "30 minutes", text.lower())
    t = re.sub(r"\ba couple of\b", "couple", t)
    t = re.sub(r"\b(an?|few|couple)\s+(hours?|minutes?|seconds?)\b", lambda m: f"{NUMBER_WORDS[m[1]]} {m[2]}", t)
    words = t.replace("-", " ").split()
    out, i = [], 0
    while i < len(words):
        w = words[i].strip(",.!?")
        if w in NUMBER_WORDS and w not in ("a", "an", "few", "couple"):
            n = NUMBER_WORDS[w]
            nxt = words[i + 1].strip(",.!?") if i + 1 < len(words) else ""
            if n >= 20 and nxt in NUMBER_WORDS and NUMBER_WORDS[nxt] < 10 and nxt not in ("a", "an"):
                n, i = n + NUMBER_WORDS[nxt], i + 1
            out.append(str(n))
        else:
            out.append(words[i])
        i += 1
    return " ".join(out)


def parse_duration(text):
    """Total seconds mentioned in the sentence, or None."""
    total = 0
    for num, unit, half in DURATION.findall(_digits(text)):
        secs = UNITS[unit]
        total += float(num) * secs + (secs / 2 if half else 0)
    return int(total) or None


def parse_reminder(text):
    """What to remind about: the part after 'to', minus any duration. 'remind me in 5 min to call mum' -> 'call mum'."""
    m = re.search(r"\bto\s+(.+)$", _digits(text))
    if not m:
        return None
    what = DURATION.sub("", m[1])
    what = re.sub(r"\bplease\b", "", what).strip(" .,!?")
    what = re.sub(r"\s*\b(in|for|after)$", "", what).strip(" .,!?")
    return what or None


def say_duration(secs):
    secs = max(0, int(round(secs)))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{n} {u}{'' if n == 1 else 's'}" for n, u in ((h, "hour"), (m, "minute"), (s, "second")) if n]
    if h or m >= 10:  # skip seconds once it's a long wait
        parts = parts[:2] if h else parts[:1]
    return " and ".join(parts) or "no time"


TIMERS, TIMERS_LOCK = [], threading.Lock()


def add_timer(secs, label=None):
    t = {"end": time.time() + secs, "secs": secs, "label": label, "line": None}
    with TIMERS_LOCK:
        TIMERS.append(t)
        TIMERS.sort(key=lambda x: x["end"])
    return t


def local_time_context():
    """Date and time for cloud prompts. Calendar events and open apps stay off this string."""
    now = datetime.now().astimezone()
    hour = int(now.strftime("%I"))
    tz = now.tzname() or "local time"
    stamp = f"{now:%A, %B} {now.day}, {now.year}, {hour}:{now:%M %p}"
    return f"Current local date and time: {stamp} ({tz}). The user is on a Mac. "


def prepare_reminder(t, said):
    """While the timer runs, have the LLM write the alert and a short name, and render the audio, so it plays instantly."""
    try:
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": f"Bearer {OR_KEY}"},
                          json={"model": LLM_MODEL, "max_tokens": 120, "response_format": {"type": "json_object"},
                                "messages": [{"role": "system", "content":
                                    local_time_context() +
                                    "The user set a reminder with a voice assistant. Reply with JSON only: "
                                    '{"label": "2 to 4 word name for the task, e.g. Call Sam", '
                                    '"alert": "one short friendly sentence the assistant says out loud when the time is up, '
                                    'speaking to the user, e.g. Hey, it\'s time to give Sam a call."}. '
                                    "The alert may start with one tag from [cheerful] [chuckling] [sighing], or none. No markdown."},
                                    {"role": "user", "content": said}]}, timeout=30)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        t["label"] = data.get("label") or t["label"]
        fetch_tts(data["alert"])  # cache the audio now
        t["line"] = data["alert"]
        print(f"\n  reminder ready: {t['label']!r} -> {t['line']!r}")
    except Exception as e:
        print(f"\n  reminder prep failed, using the plain line: {e}")


def timer_snapshot():
    """(name, seconds left) for each running timer, soonest first."""
    now = time.time()
    with TIMERS_LOCK:
        return [((t["label"] or "").capitalize() or short_duration(t["secs"]) + " timer", max(0, t["end"] - now))
                for t in TIMERS]


def short_duration(secs):
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return " ".join(f"{n} {u}" for n, u in ((h, "hr"), (m, "min"), (s, "sec")) if n) or "0 sec"


def run_timer(action, text):
    """Returns (reply_key, fmt)."""
    if action == "timer_set":
        secs = parse_duration(text)
        if not secs:
            return ("timer_unclear", {})
        label = parse_reminder(text)
        t = add_timer(secs, label)
        if label and OR_KEY:
            threading.Thread(target=prepare_reminder, args=(t, text), daemon=True).start()
        print(f"  timer: {secs}s" + (f" -> {label!r}" if label else ""))
        return ("reminder_set" if label else "timer_set", {})
    with TIMERS_LOCK:
        if not TIMERS:
            return ("timer_none", {})
        if action == "timer_check":
            return ("timer_check", {"left": say_duration(TIMERS[0]["end"] - time.time())})
        if re.search(r"\ball\b", text.lower()):
            TIMERS.clear()
            return ("timers_cancel", {})
        TIMERS.remove(max(TIMERS, key=lambda t: t["end"] - t["secs"]))  # the one set most recently
        return ("timer_cancel", {})


def start_timer_loop(on_done):
    """Fires on_done(timer) when a timer runs out."""
    def loop():
        while True:
            time.sleep(0.25)
            with TIMERS_LOCK:
                due = [t for t in TIMERS if t["end"] <= time.time()]
                for t in due:
                    TIMERS.remove(t)
            for t in due:
                try:
                    on_done(t)
                except Exception as e:
                    print(f"  timer alert failed: {e}")
    threading.Thread(target=loop, daemon=True).start()


def timer_done_line(t):
    if t["line"]:
        return t["line"]
    return say_line("reminder_done", label=t["label"]) if t["label"] else say_line("timer_done")


# --------------------------------------------------------------------------- LLM fallback (questions only)
LLM_MODEL = "anthropic/claude-haiku-4.5"


def ask_llm(text):
    t = time.time()
    r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                      headers={"Authorization": f"Bearer {OR_KEY}"},
                      json={"model": LLM_MODEL, "max_tokens": 80, "usage": {"include": True},
                            "messages": [{"role": "system", "content": local_time_context() +
                                          "You are a voice assistant. Answer in one short spoken sentence, no markdown. "
                                          "You may start with exactly one tag from: [chuckling] [laughing] [sighing] [cheerful], or none."},
                                         {"role": "user", "content": text}]}, timeout=30)
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"].strip(), int((time.time() - t) * 1000), j.get("usage", {}).get("cost")


# --------------------------------------------------------------------------- Decision
def _picked(key, arg=None, reply=None, fmt=None, conf=0.95):
    return (conf, key, arg, reply or key, fmt or {})


def sub_action(ans, target):
    """(conf, action_key, arg, reply_key, fmt) for a target, or None if Jev didn't pick anything confident."""
    if target == "app":
        (app, ac), (action, aac) = ans["app"], ans["app_action"]
        if action not in ("open", "quit") or aac < GATE:
            return None
        if app not in APPS:
            # "other" / "none": the real name is parsed from the transcript, not from this enum.
            app, conf, display = "other", aac, ""
        elif ac < GATE:
            return None
        else:
            conf, display = min(ac, aac), APPS[app]
        return (conf, f"app_{action}", app, f"app_{action}", {"app": display or "that app"})
    key = {"volume": "volume_action", "display": "display_action", "media": "media_action",
           "system": "system_action", "timer": "timer_action", "info": "info_action",
           "shortcut": "shortcut_action"}.get(target)
    if key is None or key not in ans:
        return None
    action, conf = ans[key]
    if action == "none" or conf < GATE:
        return None
    if target == "info":
        return (conf, f"info_{action}", None, f"info_{action}", {})
    if target == "shortcut":
        return (conf, "shortcut_run", None, "shortcut_run", {}) if action == "run" else None
    lvl = ans["volume_level"][0] if target == "volume" else None
    prefix = target
    if target == "volume":
        scope, scope_conf = ans["volume_scope"]
        named_spotify = ans["app"][0] == "spotify"
        if scope == "spotify" and (scope_conf >= 0.5 or named_spotify):
            prefix = "spotify_volume"
    return (conf, f"{prefix}_{action}", lvl, f"{prefix}_{action}", {"level": lvl})


def decide(ans, text=""):
    """Read the Jev fan-out. Returns ("actions", [...]), ("reply", key), ("llm", None) or ("clarify", None).

    Time, date, calendar, open apps, and a named shortcut are routed here before the
    information_request -> LLM branch. Quit-all is never one half of a two-part command.
    """
    cat, cconf = ans["category"]
    # compound[0] is the yes/no. A weak yes still blocks the single-action fast paths,
    # matching the original timer check; only a confident yes is actually split.
    raw_compound = bool(ans["compound"][0])
    compound = raw_compound and ans["compound"][1] >= GATE
    if commands.is_quit_all(text):
        if commands.quit_all_is_compound(text, raw_compound):
            return ("reply", "quit_all_alone")
        return ("actions", [_picked("apps_quit_all")])
    # Clear local phrases, before the timer route and before Haiku.
    if not raw_compound:
        local = commands.preview_action(text)
        if local:
            return ("actions", [_picked(local)])
    if ans["target"][0] == "timer" and ans["target"][1] >= GATE and not raw_compound:
        t = sub_action(ans, "timer")  # "how long is left?" reads like a question but it's a timer command
        if t:
            return ("actions", [t])
    # Paraphrases Jev marked as info ("got the time?", "anything on today?") also stay local.
    if not raw_compound and ans["target"][0] == "info" and ans["target"][1] >= 0.5:
        info = sub_action(ans, "info")
        if info:
            return ("actions", [info])
    if not raw_compound and ans["target"][0] == "shortcut" and ans["target"][1] >= 0.5:
        shortcut = sub_action(ans, "shortcut")
        if shortcut:
            return ("actions", [shortcut])
    if cat == "chit_chat" and cconf >= GATE:
        return ("reply", "chit_chat")
    if cat == "information_request" and cconf >= GATE:
        return ("llm", None)
    if cat == "unclear" and cconf >= GATE:
        return ("clarify", None)
    if compound:
        return ("split", None)
    a = pick_action(ans)
    if a:
        return ("actions", [a])
    return ("llm", None) if cat == "information_request" else ("clarify", None)


def pick_action(ans):
    """Trust Jev's target if it's reasonably sure, else take the single most confident action anywhere."""
    target, tconf = ans["target"]
    a = sub_action(ans, target) if tconf >= 0.5 else None
    if a is None:
        cands = [x for x in (sub_action(ans, t) for t in TARGETS) if x]
        a = max(cands, key=lambda x: x[0]) if cands else None
    return a


def split_actions(text, ans):
    """Second Jev call with first/second slots, so two actions in one sentence each get their own answers."""
    sans, ms, cost = jev(text, SPLIT_QUESTIONS)
    print(f"  -- split call: jev {ms}ms  ${cost:.6f}")
    acts = []
    for slot in ("first", "second"):
        half = {k[len(slot) + 1:]: v for k, v in sans.items() if k.startswith(slot + "_")}
        a = pick_action(half)
        print(f"  {slot:15} {a[1] if a else 'nothing confident'}" + (f" {a[2]}" if a and a[2] else ""))
        if a and (a[1], a[2]) not in [(x[1], x[2]) for x in acts]:
            acts.append(a)
    if len(acts) < 2:  # split didn't separate them, fall back to whatever the first fan-out was sure about
        acts = [a for a in (sub_action(ans, t) for t in TARGETS) if a]
    return acts


# --------------------------------------------------------------------------- Fish TTS
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "tts")


def fetch_tts(text):
    """Return a wav path for this line, generating it once and caching on disk. Returns (path, ms, cached)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(f"{VOICE_ID}|{text}".encode()).hexdigest() + ".wav")
    if os.path.exists(path):
        return path, 0, True
    t = time.time()
    r = requests.post("https://api.fish.audio/v1/tts", headers={"Authorization": f"Bearer {FISH_KEY}", "model": "s2.1-pro-free"},
                      json={"text": text, "reference_id": VOICE_ID, "format": "wav"}, timeout=60)
    r.raise_for_status()
    open(path, "wb").write(r.content)
    return path, int((time.time() - t) * 1000), False


def speak(text):
    path, ms, cached = fetch_tts(text)
    subprocess.run(["afplay", path])
    return ms


def all_scripted_lines():
    """Every fixed reply with placeholders expanded, so the whole set can be pre-rendered.

    {app} expands only over APPS. Lines for any other installed app, and live answers
    such as the time or a calendar title, are generated when they are spoken.
    """
    for key, lines in REPLIES.items():
        for line in lines:
            if "{app}" in line:
                yield from (line.format(app=a) for a in APPS.values())
            elif "{level}" in line:
                yield from (line.format(level=l) for l in LEVELS)
            elif "{" not in line:  # lines with a live value like {left} are generated when needed
                yield line


def warm_cache():
    """Pre-render all scripted lines in the background so replies play instantly ($0 on the free string)."""
    made = 0
    for line in all_scripted_lines():
        try:
            _, _, cached = fetch_tts(line)
            made += 0 if cached else 1
        except Exception as e:
            print(f"  cache miss for {line!r}: {e}")
    if made:
        print(f"  cached {made} new reply lines")


# --------------------------------------------------------------------------- One turn
misses = 0


def emit(notify, state, detail=""):
    if notify:
        notify(state, detail)


def _speak_result(action, result, reply_key, fmt):
    """A string is spoken as-is. A dict fills the scripted reply (used for {app})."""
    if isinstance(result, str):
        return result
    merged = {**fmt, **result} if isinstance(result, dict) else fmt
    if reply_key in REPLIES:
        return say_line(reply_key, **merged)
    return say_line("unsupported")


def _finish_confirmed(notify):
    """Run the action that was armed by a previous turn. The yes was already checked locally."""
    action, arg, source, reply_key, fmt = commands.take_confirmation()
    print(f"  confirm: yes -> {action} (local, no api)")
    try:
        emit(notify, "Doing it", source or "")
        result = ACTIONS[action](arg, source or "")
        print(f"  action: {action} {arg or ''}")
        line = _speak_result(action, result, reply_key, fmt)
    except Exception as e:
        print(f"  action failed: {action} {e}")
        line = say_line("unsupported")
    say(line, notify)
    emit(notify, "Ready", line)


def handle(text, stt_ms=None, notify=None):
    global misses
    print(f"\n> heard: {text!r}" + (f"  (stt {stt_ms}ms)" if stt_ms is not None else ""))
    if not text.strip():
        emit(notify, "Ready", "Didn't catch anything")
        return
    # A pending yes/no is decided here, before Jev or any other request.
    pending = commands.confirmation_status(text)
    if pending == "yes":
        misses = 0
        _finish_confirmed(notify)
        return
    if pending == "no":
        commands.clear_confirmation()
        misses = 0
        print("  confirm: no (local, no api)")
        line = say_line("confirm_no")
        say(line, notify)
        emit(notify, "Ready", line)
        return
    if pending in ("expired", "other"):
        print(f"  confirm: {pending}, handling this as a new request")
    emit(notify, "Thinking", text)
    ans, jev_ms, cost = jev(text)
    for k, (v, c) in ans.items():
        flag = "" if c >= GATE else "  <- below gate"
        print(f"  {k:15} {str(v):22} {c:.2f}{flag}")
    print(f"  jev {jev_ms}ms  ${cost:.6f}")
    kind, payload = decide(ans, text)
    if kind == "split":
        payload = commands.isolate_confirmations(split_actions(text, ans))
        kind = "actions" if payload else "clarify"
    elif kind == "actions":
        payload = commands.isolate_confirmations(payload)
    armed = False
    if kind == "clarify":
        misses += 1
        line = say_line("give_up") if misses >= 2 else say_line("clarify")
        if misses >= 2:
            misses = 0
    else:
        misses = 0
        if kind == "reply":
            line = say_line(payload)
        elif kind == "llm":
            line, llm_ms, llm_cost = ask_llm(text)
            print(f"  llm {LLM_MODEL} {llm_ms}ms  ${llm_cost}")
        else:
            default_line = lambda: say_line(payload[0][3], **payload[0][4]) if len(payload) == 1 else say_line("compound_done")
            # anything that kills the sound or the screen gets the reply first, or she'd mute herself
            speak_first = any(a[1] in SPEAK_FIRST or (a[1].endswith("volume_set") and a[2] == "silent") for a in payload)
            if speak_first:
                line = default_line()
                say(line, notify)
            done, timer_reply, dynamic, fmt_override = 0, None, [], {}
            for _, action, arg, reply_key, fmt in payload:
                if action in commands.CONFIRM:
                    # Ask first. A second action in the same utterance was already dropped.
                    if len(payload) > 1:
                        dynamic = [say_line("quit_all_alone")]
                        done += 1
                        break
                    commands.arm_confirmation(action, arg, text, reply_key, fmt)
                    dynamic = [say_line(reply_key) if reply_key in REPLIES else "Say yes to confirm."]
                    armed = True
                    done += 1
                    print(f"  confirm: waiting for yes/no on {action}")
                    break
                try:
                    emit(notify, "Doing it", text)
                    if action.startswith("timer_"):
                        timer_reply = run_timer(action, text)
                    else:
                        result = ACTIONS[action](arg, text)
                        if isinstance(result, str):
                            dynamic.append(result)
                        elif isinstance(result, dict):
                            fmt_override.update(result)
                    print(f"  action: {action} {arg or ''}")
                    done += 1
                except Exception as e:
                    print(f"  action failed: {action} {e}")
            if speak_first:
                emit(notify, "Ready", line)
                return
            if not done:
                line = say_line("unsupported")
            elif dynamic and len(payload) == 1:
                line = dynamic[0]
            elif timer_reply and len(payload) == 1:
                line = say_line(timer_reply[0], **timer_reply[1])
            elif len(payload) == 1 and payload[0][3] in REPLIES:
                line = say_line(payload[0][3], **{**payload[0][4], **fmt_override})
            elif dynamic:
                line = " ".join(dynamic + [say_line("compound_done")])
            elif len(payload) == 1:
                line = say_line("unsupported")
            else:
                line = default_line()
    say(line, notify)
    emit(notify, "Ready", line)
    if armed:
        # The 10 seconds start after the prompt, so speaking it doesn't eat the window.
        commands.refresh_confirmation()
        return "expect_reply"


def say(line, notify):
    print(f"  say: {line}")
    emit(notify, "Speaking", line)
    tts_ms = speak(line)
    print(f"  fish {'cached' if tts_ms == 0 else str(tts_ms) + 'ms'}")


# --------------------------------------------------------------------------- Mic + push to talk
class Recorder:
    BLOCK = 1600  # 100ms at 16kHz

    def __init__(self):
        self.frames, self.on = [], False
        self.wake, self.paused = False, False
        self.segments = queue.Queue()
        self.noise = 0.005
        self._reset_segment()
        self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                     blocksize=self.BLOCK, callback=self._cb)
        self.stream.start()

    def _reset_segment(self):
        self.speech, self.silent = [], 0
        self.preroll = collections.deque(maxlen=3)

    def _cb(self, indata, *_):
        if self.on:
            self.frames.append(indata.copy())
        if not self.wake or self.paused:
            if self.speech:
                self._reset_segment()
            return
        block = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(block ** 2)))
        loud = rms > max(self.noise * 3, 0.01)
        if not self.speech:
            if loud:
                self.speech, self.silent = list(self.preroll) + [block], 0
            else:
                self.noise = 0.95 * self.noise + 0.05 * rms  # track the room's background level
                self.preroll.append(block)
            return
        self.speech.append(block)
        self.silent = 0 if loud else self.silent + 1
        if self.silent >= 8 or len(self.speech) >= 150:  # 0.8s pause ends a phrase, 15s max
            if len(self.speech) - self.silent >= 4:
                self.segments.put(np.concatenate(self.speech))
            self._reset_segment()

    def start(self):
        self.frames, self.on = [], True

    def stop(self):
        self.on = False
        return np.concatenate(self.frames)[:, 0] if self.frames else np.zeros(0, dtype="float32")


def ready_text(wake):
    return "Say \u201cHey Jev\u201d and your command" if wake else "Ready when you are"


def run_voice_assistant(notify=None, controls=None, mode="ptt"):
    from faster_whisper import WhisperModel
    print("loading whisper...")
    emit(notify, "Starting", "Loading Whisper\u2026")
    model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
    rec = Recorder()
    busy = threading.Lock()
    armed_until = [0.0]

    def transcribe(audio, prompt):
        t = time.time()
        segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True, initial_prompt=prompt)
        return " ".join(s.text.strip() for s in segs).strip(), int((time.time() - t) * 1000)

    def run_turn(text, stt_ms):
        with busy:
            rec.paused = True  # don't hear her own reply
            try:
                result = handle(text, stt_ms, notify)
                # Wake mode: she just asked for a yes/no, so the next phrase doesn't need "Hey Jev".
                if result == "expect_reply" and rec.wake:
                    armed_until[0] = time.time() + commands.CONFIRM_SECONDS
                    emit(notify, "Listening", "Say yes to confirm, or no to cancel")
            except Exception as exc:
                print(f"\n  turn failed: {exc}")
                emit(notify, "Something went wrong", str(exc))
                time.sleep(2)
                emit(notify, "Ready", ready_text(rec.wake))
            finally:
                time.sleep(0.3)
                rec.paused = False

    def ptt_turn(audio):
        emit(notify, "Transcribing", "Working out what you said\u2026")
        try:
            text, ms = transcribe(audio, COMMAND_PROMPT)
        except Exception as exc:
            emit(notify, "Something went wrong", str(exc))
            return
        run_turn(text, ms)

    def wake_loop():
        while True:
            try:
                audio = rec.segments.get(timeout=1)
            except queue.Empty:
                if armed_until[0] and time.time() > armed_until[0]:
                    armed_until[0] = 0
                    emit(notify, "Ready", ready_text(rec.wake))
                continue
            if not rec.wake or busy.locked():
                continue
            try:
                text, ms = transcribe(audio, WAKE_PROMPT)
            except Exception as exc:
                print(f"\n  transcribe failed: {exc}")
                continue
            m = WAKE.match(text)
            if m:
                rest = text[m.end():].strip(" .,!?")
                if rest:
                    armed_until[0] = 0
                    run_turn(rest, ms)
                else:
                    with busy:
                        rec.paused = True
                        say(say_line("wake"), notify)
                        time.sleep(0.2)
                        rec.paused = False
                    armed_until[0] = time.time() + WAKE_WINDOW
                    emit(notify, "Listening", "Go ahead\u2026")
            elif armed_until[0] and time.time() < armed_until[0]:
                armed_until[0] = 0
                run_turn(text, ms)
            elif text:
                print(f"\n  (not for me: {text!r})")

    def set_mode(new):
        rec.wake = new == "wake"
        armed_until[0] = 0
        print(f"\n[mode: {'always listening' if rec.wake else 'hold right Option'}]")
        if not busy.locked():
            emit(notify, "Ready", ready_text(rec.wake))

    def start_recording():
        if not rec.wake and not rec.on and not busy.locked():
            rec.start()
            print("\n[listening]", end="", flush=True)
            emit(notify, "Listening", "Release right Option when you\u2019re done")

    def stop_recording():
        if rec.on:
            audio = rec.stop()
            if len(audio) > SAMPLE_RATE * 0.3:
                threading.Thread(target=ptt_turn, args=(audio,), daemon=True).start()

    def timer_done(t):
        with busy:
            rec.paused = True
            try:
                emit(notify, "Time's up", t["label"] or "Timer finished")
                subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"])
                say(timer_done_line(t), notify)
            finally:
                time.sleep(0.3)
                rec.paused = False
        emit(notify, "Ready", ready_text(rec.wake))

    start_timer_loop(timer_done)
    threading.Thread(target=warm_cache, daemon=True).start()
    threading.Thread(target=wake_loop, daemon=True).start()
    set_mode(mode)
    print("ready. ctrl+c to quit.")
    if controls is not None:
        while True:
            command = controls.get()
            if isinstance(command, tuple) and command[0] == "mode":
                set_mode(command[1])
            elif command == "press":
                start_recording()
            elif command == "release":
                stop_recording()

    if rec.wake:
        threading.Event().wait()

    def on_press(key):
        if key == PTT_KEY:
            start_recording()

    def on_release(key):
        if key == PTT_KEY:
            stop_recording()

    with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
        l.join()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="skip the mic, run one turn on this transcript")
    ap.add_argument("--ui", action="store_true", help="show the native floating status window")
    ap.add_argument("--wake", action="store_true", help="always listening, say \"Hey Jev\" instead of holding Option")
    args = ap.parse_args()
    if args.ui:
        from assistant_ui import run_app
        run_app()
        return
    if not TS_KEY or not FISH_KEY:
        sys.exit("need TYPESAFE_API_KEY and FISH_AUDIO_API_KEY in Keychain or .env")
    if args.text:
        handle(args.text)
        return
    run_voice_assistant(mode="wake" if args.wake else "ptt")


if __name__ == "__main__":
    main()
