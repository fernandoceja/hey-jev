"""No models, network, sockets, child processes, or playback: mocked boundaries."""
import ast
import json
import os
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
import wave

import pytest

from commands import omnivoice_voice as native
from commands.omnivoice_profiles import Profiles
from commands.omnivoice_worker import handle, main as worker_main


def wav(path):
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 24000, 0, "NONE", "none"))
        stream.writeframes(b"\0\0" * 240)


@pytest.fixture
def boundary():
    process = MagicMock()
    process.poll.return_value = None
    process.stdout.fileno.return_value = 123
    selector = MagicMock()
    selector.select.return_value = [(None, None)]
    with patch.object(native, "runtime_python", return_value="existing/python"), \
            patch.object(native.subprocess, "Popen", return_value=process) as popen, \
            patch.object(native.selectors, "DefaultSelector") as factory, \
            patch.object(native.os, "read", return_value=b'{"ok": true}\n') as read, \
            patch.object(native.os, "set_blocking"), \
            patch.object(native.os, "write") as write, \
            patch.object(native.threading, "Timer") as timer:
        factory.return_value.__enter__.return_value = selector
        def render(message):
            wav(json.loads(message)["output"])
        def send(fd, message):
            render(message)
            process.stdin.write(message)
            return len(message)
        write.side_effect = send
        yield process, popen, selector, read, timer


def test_lazy_warm_idle_and_offline(tmp_path, boundary):
    process, popen, _, _, timer = boundary
    worker = native.Worker()
    popen.assert_not_called()
    for i in range(2):
        result = worker.render("Hello", tmp_path / (str(i) + ".wav"))
        assert not result[2]
    popen.assert_called_once()
    options = popen.call_args.kwargs
    assert options["env"]["HF_HUB_OFFLINE"] == "1"
    assert options["env"]["TRANSFORMERS_OFFLINE"] == "1"
    assert popen.call_args.args[0] == ["existing/python", "-m", "commands.omnivoice_worker"]
    assert json.loads(process.stdin.write.call_args.args[0])["voice"] == "default"
    assert timer.call_args.args[0] == 120
    worker._expire()
    process.kill.assert_called_once()
    assert worker.process is None and not worker.disabled
    worker.render("Reload", tmp_path / "reload.wav")
    assert popen.call_count == 2
    worker.close()


@pytest.mark.parametrize("failure", ["crash", "timeout", "cancel", "bad_json", "oversize", "engine", "invalid_audio"])
def test_failures_kill_disable_and_preserve_output(tmp_path, boundary, failure):
    process, popen, selector, read, _ = boundary
    worker = native.Worker(timeout=.001 if failure == "timeout" else 1)
    output = tmp_path / "saved.wav"
    output.write_bytes(b"previous")
    cancel = None
    if failure == "crash":
        read.return_value = b""
    elif failure == "timeout":
        selector.select.return_value = []
    elif failure == "cancel":
        cancel = MagicMock()
        cancel.is_set.side_effect = [False, True]
    elif failure == "bad_json":
        read.return_value = b"garbage\n"
    elif failure == "oversize":
        read.return_value = b"x" * 65537
    elif failure == "engine":
        read.return_value = b'{"ok": false, "error": "MissingModel"}\n'
    else:
        native.os.write.side_effect = lambda fd, message: len(message)
    with pytest.raises(Exception):
        worker.render("Hello", output, cancel=cancel)
    assert worker.disabled and worker.process is None
    assert output.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [output]
    with pytest.raises(RuntimeError):
        worker.render("Again", output)
    popen.assert_called_once()
    process.kill.assert_called_once()
    worker.reset()
    assert not worker.disabled


@pytest.mark.parametrize("text,filename", [("", "a.wav"), ("x" * 4097, "a.wav"), ("hi", "a.mp3")])
def test_request_bounds_before_spawn(tmp_path, text, filename):
    with patch.object(native.subprocess, "Popen") as popen:
        with pytest.raises(ValueError):
            native.Worker().render(text, tmp_path / filename)
        popen.assert_not_called()


def test_worker_protocol_engine_boundary(tmp_path):
    request = {"model": "omnivoice", "input": "Hello", "voice": "default",
               "response_format": "wav", "output": str(tmp_path / "audio.wav")}
    engine = MagicMock()
    factory = MagicMock(return_value=engine)
    assert handle(request, factory)["provider"] == "OMNIVOICE"
    engine.render.assert_called_once_with(request, request["output"])
    for change in ({"model": "fish"}, {"input": ""}, {"voice": "unknown"}, {"response_format": "mp3"}):
        with pytest.raises(ValueError):
            handle(dict(request, **change), factory)
    import io
    # EOF never loads a model; oversized input exits without parsing or loading.
    for data in (b"", b"x" * 65537):
        with patch("sys.stdin", type("Input", (), {"buffer": io.BytesIO(data)})()), \
                patch.dict(sys.modules, {"commands.omnivoice_engine": MagicMock()}) as modules:
            worker_main()
            modules["commands.omnivoice_engine"].Engine.assert_not_called()


def test_profiles_consent_copy_persist_import_and_pronunciation(tmp_path):
    source_dir = tmp_path / "voices"
    source_dir.mkdir()
    source = source_dir / "original.wav"
    wav(source)
    original = source.read_bytes()
    db = source_dir / "omnivoice.db"
    db.write_bytes(b"untouched")
    store = Profiles(tmp_path / "jev")
    with pytest.raises(ValueError):
        store.create("Voice", source)
    assert not store.root.exists()
    profile = store.create("Voice", source, consent=True,
                           settings={"pronunciation": {"Jev": "Jeev"}, "ref_text": "Hello"})
    assert profile["name"] == "Voice" and profile["created"]
    assert profile["reference_wav"] != str(source)
    assert Profiles(store.root).load("Voice") == profile
    worker = MagicMock()
    store.render("Voice", "Jev speaks", tmp_path / "spoken.wav", worker)
    assert worker.render.call_args.args[0] == "Jeev speaks"
    assert worker.render.call_args.kwargs["settings"] == {"ref_text": "Hello"}
    with pytest.raises(FileExistsError):
        store.create("Voice", source, consent=True)
    store.import_voice("Imported", "original.wav", consent=True, source_dir=source_dir)
    assert source.read_bytes() == original and db.read_bytes() == b"untouched"
    for filename in ("omnivoice.db", "../voices/../not.wav"):
        with pytest.raises((ValueError, FileNotFoundError)):
            store.import_voice("Bad", filename, consent=True, source_dir=source_dir)
    with pytest.raises(ValueError):
        store.create("../escape", source, consent=True)


def test_design_cli_explicit_output_and_cleanup(tmp_path):
    from scripts.omnivoice import main
    with patch("scripts.omnivoice.Worker") as factory:
        factory.return_value.render.return_value = ("line.wav", 1, False)
        main(["design", "--description", "Warm storybook narrator", "--text", "Once upon a time",
              "--output", str(tmp_path / "line.wav")])
        factory.return_value.render.assert_called_once_with("Once upon a time", str(tmp_path / "line.wav"),
                                                            description="Warm storybook narrator")
        factory.return_value.close.assert_called_once()
    with pytest.raises(SystemExit):
        main(["design", "--description", "Warm", "--text", "Hello"])


def extracted(name):
    source = Path(__file__).resolve().parents[1] / "siri.py"
    node = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), str(source), "exec")


def test_native_fallback_order_and_existing_session_skip(tmp_path):
    # Real VoiceStudio session guard, mocked HTTP-free implementation.
    with patch.dict(sys.modules, {"requests": MagicMock()}):
        from commands import voicestudio_voice as vs
    vs.reset_session()
    commands = MagicMock()
    commands.synthesize_speech.return_value = type("Speech", (), {"path": "fish.wav", "ms": 2, "cached": False})()
    namespace = dict(os=os, CACHE_DIR=str(tmp_path), commands=commands, voicestudio_voice=vs,
                     requests=MagicMock(), FISH_KEY="unused", VOICE_ID="unused")
    exec(extracted("fetch_tts"), namespace)
    with patch.dict(os.environ, {"JEV_TTS_PROVIDER": "OMNIVOICE"}), \
            patch.object(native, "fetch_speech", return_value=("native.wav", 1, False)) as fetch, \
            patch.object(vs, "_fetch_speech", side_effect=RuntimeError("offline")) as legacy:
        assert namespace["fetch_tts"]("Hello")[0] == "native.wav"
        legacy.assert_not_called()
        fetch.side_effect = RuntimeError("worker died")
        for _ in range(2):
            assert namespace["fetch_tts"]("Hello")[0] == "fish.wav"
        legacy.assert_called_once()
    vs.reset_session()


@pytest.mark.parametrize("error", [None, RuntimeError("error"), KeyboardInterrupt()])
def test_speaking_ready_on_success_error_cancel(error):
    emit = MagicMock()
    speak = MagicMock(return_value=1, side_effect=error)
    namespace = {"emit": emit, "speak": speak}
    exec(extracted("say"), namespace)
    if error is None:
        namespace["say"]("Hello", None)
    else:
        with pytest.raises(type(error)):
            namespace["say"]("Hello", None)
    assert [call.args[1] for call in emit.call_args_list] == ["Speaking", "Ready"]


def test_live_report_mocked_series_and_pending(tmp_path):
    from scripts import omnivoice_live_test as live
    worker = MagicMock()
    worker.process.poll.return_value = 0
    # idle check sees a released process after measuring the pre-idle RSS.
    def sample(pid):
        worker.process = None
        return 1024
    def measurement(instance, text, path):
        instance.process = MagicMock()
        instance.process.poll.return_value = 0
        return {"peak_worker_rss_bytes": 2048, "input": text, "output": str(path)}
    def fail(*args):
        worker.disabled = True
        raise RuntimeError("crashed")
    worker.render.side_effect = fail
    with patch.object(live, "Worker", return_value=worker), \
            patch.object(live, "runtime_python", return_value="runtime"), \
            patch.object(live.platform, "platform", return_value="Mock Mac"), \
            patch.object(live, "measure", side_effect=measurement), patch.object(live, "rss", side_effect=sample):
        report = live.run(tmp_path, idle=.01)
    assert report["gate"] == "PENDING"
    assert report["automated_checks_passed"]
    assert set(report["measurements"]) == {"cold", "warm_short", "long", "recovered"}
    assert json.loads((tmp_path / "report.json").read_text())["provider"] == "OMNIVOICE"
    worker.close.assert_called_once()


def test_engine_offline_and_api_assumptions(tmp_path):
    from commands.omnivoice_engine import Engine
    hf, model_module, sf = MagicMock(), MagicMock(), MagicMock()
    hf.snapshot_download.return_value = str(tmp_path)
    with patch.dict(sys.modules, {"huggingface_hub": hf, "omnivoice": model_module, "soundfile": sf}):
        engine = Engine()
        engine.render({"input": "Hello", "description": "Soft", "reference": "ref.wav", "settings": {}}, "out.wav")
        assert hf.snapshot_download.call_args.kwargs["local_files_only"]
        assert model_module.OmniVoice.from_pretrained.call_args.kwargs["local_files_only"]
        engine.model.generate.assert_called_once_with(text="Hello", instruct="Soft", ref_audio="ref.wav")
        sf.write.assert_called_once()
        with pytest.raises(ValueError):
            engine.render({"input": "Hello", "settings": {"unexpected": True}}, "out.wav")


def test_new_entrypoints_have_no_playback_or_listener_calls():
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "commands").glob("omnivoice*.py")) + list((root / "scripts").glob("omnivoice*.py"))
    forbidden = {"socket", "bind", "listen", "serve_forever", "play", "afplay", "playsound"}
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = node.func
                name = called.attr if isinstance(called, ast.Attribute) else getattr(called, "id", "")
                assert name not in forbidden, str(path)


def test_live_report_records_missing_runtime_without_model_load(tmp_path):
    from scripts import omnivoice_live_test as live
    with patch.object(live.platform, "platform", return_value="Mock Mac"), \
            patch.object(live, "runtime_python", side_effect=RuntimeError("Missing runtime")), \
            patch.object(live, "measure") as measure:
        report = live.run(tmp_path)
    measure.assert_not_called()
    assert not report["automated_checks_passed"] and report["gate"] == "PENDING"
    assert "Missing runtime" in report["error"]
