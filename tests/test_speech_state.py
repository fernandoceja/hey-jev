"""Execute speech helpers without app startup or audio dependencies."""
import ast
from pathlib import Path
import threading
import time
from unittest.mock import MagicMock

import pytest


def helpers():
    source = Path(__file__).resolve().parents[1] / "siri.py"
    nodes = [n for n in ast.parse(source.read_text()).body
             if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in {"say", "say_local", "emit", "BriefAudio"}]
    namespace = {"speak": MagicMock(return_value=0), "subprocess": MagicMock(),
                 "threading": threading, "time": time}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("name", ["say", "say_local"])
@pytest.mark.parametrize("fails", [False, True])
def test_speech_always_clears_speaking(name, fails):
    ns = helpers()
    events = []
    play = ns["speak"] if name == "say" else ns["subprocess"].run
    if fails:
        play.side_effect = OSError("playback failed")
    if fails and name == "say":
        with pytest.raises(OSError):
            ns[name]("Hello.", lambda *event: events.append(event))
    else:
        ns[name]("Hello.", lambda *event: events.append(event))
    assert events[0][0] == "Speaking"
    assert events[-1][0] == "Ready"
    play.assert_called_once()


@pytest.mark.parametrize("outcome", ["success", "failure", "discard", "start_failure"])
def test_brief_playback_clears_speaking(outcome):
    ns = helpers()
    audio = ns["BriefAudio"]()
    audio.chunks = ["Hello."]
    audio.paths = ["test.wav"]
    audio.events = [threading.Event()]
    audio.events[0].set()
    workers = []

    def thread(target, **kwargs):
        worker = MagicMock()
        if outcome == "start_failure":
            worker.start.side_effect = RuntimeError("cannot start")
        else:
            worker.start.side_effect = lambda: workers.append(target)
        return worker

    ns["threading"] = MagicMock(Thread=thread)
    events = []
    notify = lambda *event: events.append(event)
    if outcome == "start_failure":
        with pytest.raises(RuntimeError):
            audio.play(notify)
    else:
        audio.play(notify)
        if outcome == "failure":
            ns["subprocess"].run.side_effect = OSError("playback failed")
            with pytest.raises(OSError):
                workers[-1]()
        else:
            if outcome == "discard":
                audio.discard()
            workers[-1]()
    assert events[0][0] == "Speaking"
    assert events[-1][0] == "Ready"
