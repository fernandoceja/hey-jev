"""Offline provider contract and download/consent guards."""
import ast
import io
import os
import tempfile
import sys
import unittest
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

# CI deliberately installs only pytest; all HTTP is mocked in this offline contract.
with patch.dict(sys.modules, {"requests": MagicMock()}):
    from commands import voicestudio_voice as vs


class VoiceStudioTests(unittest.TestCase):
    def setUp(self):
        vs.reset_session()
        self.addCleanup(vs.reset_session)

    def test_shared_reply_path_keeps_fish_default_and_fallback(self):
        # Execute the actual shared fetch function without app/Keychain startup.
        source = Path(__file__).resolve().parents[1] / "siri.py"
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch_tts")
        commands = MagicMock()
        commands.synthesize_speech.return_value = type("Speech", (), {
            "path": "fish.wav", "ms": 42, "cached": False})()
        adapter = MagicMock()
        with tempfile.TemporaryDirectory() as folder:
            namespace = {"os": os, "CACHE_DIR": folder, "commands": commands,
                         "voicestudio_voice": adapter, "requests": MagicMock(),
                         "FISH_KEY": "unused", "VOICE_ID": "existing"}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            adapter.provider.return_value = "FISH"
            self.assertEqual(namespace["fetch_tts"]("Hello."), ("fish.wav", 42, False))
            adapter.fetch_speech.assert_not_called()
            commands.synthesize_speech.reset_mock()
            adapter.provider.return_value = "VOICESTUDIO"
            adapter.fetch_speech.return_value = ("local.wav", 10, False)
            self.assertEqual(namespace["fetch_tts"]("Hello."), ("local.wav", 10, False))
            commands.synthesize_speech.assert_not_called()
            adapter.fetch_speech.side_effect = RuntimeError("unavailable")
            self.assertEqual(namespace["fetch_tts"]("Hello."), ("fish.wav", 42, False))
            commands.synthesize_speech.assert_called_once()

    def test_unreachable_falls_back_once_for_the_session(self):
        source = Path(__file__).resolve().parents[1] / "siri.py"
        function = next(n for n in ast.parse(source.read_text()).body
                        if isinstance(n, ast.FunctionDef) and n.name == "fetch_tts")
        commands = MagicMock()
        commands.synthesize_speech.return_value = type("Speech", (), {
            "path": "fish.wav", "ms": 42, "cached": False})()
        session = self.session()
        session.get.side_effect = ConnectionError("refused")
        with tempfile.TemporaryDirectory() as folder, patch.object(vs.requests, "Session") as client, patch.dict(os.environ, {"JEV_TTS_PROVIDER": "VOICESTUDIO"}):
            client.return_value.__enter__.return_value = session
            namespace = {"os": os, "CACHE_DIR": folder, "commands": commands,
                         "voicestudio_voice": vs, "requests": MagicMock(),
                         "FISH_KEY": "unused", "VOICE_ID": "existing"}
            exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
            for line in ("Hello.", "Another line.", "A drama notice."):
                self.assertEqual(namespace["fetch_tts"](line), ("fish.wav", 42, False))
            client.assert_called_once()
            session.get.assert_called_once_with(vs.BASE_URL + "/models", timeout=(1, 3))
            session.post.assert_not_called()
            self.assertEqual(commands.synthesize_speech.call_count, 3)
            vs.reset_session()
            session.get.side_effect = None
            self.assertTrue(namespace["fetch_tts"]("Recovered.")[0].endswith(".wav"))
            self.assertEqual(client.call_count, 2)

    def test_fish_is_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(vs.provider(), "FISH")

    def session(self, installed=True, accepted=True):
        session = MagicMock()
        session.get.return_value.json.return_value = {"models": [{
            "repo_id": vs.MODEL_REPO, "installed": installed, "incomplete": False,
            "license_acceptance": {"required": True, "accepted": accepted}}]}
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * 240)
        session.post.return_value.content = buffer.getvalue()
        return session

    def test_request_audio_and_cache(self):
        session = self.session()
        with tempfile.TemporaryDirectory() as folder, patch.object(vs.requests, "Session") as client, patch.dict(os.environ, {"JEV_VOICESTUDIO_VOICE": "demo0001"}):
            client.return_value.__enter__.return_value = session
            path, _, cached = vs.fetch_speech("Hello.", folder)
            self.assertTrue(os.path.isfile(path))
            self.assertFalse(cached)
            self.assertEqual(session.post.call_args.kwargs['json'], {
                "model": "omnivoice", "input": "Hello.", "voice": "demo0001", "response_format": "wav"})
            self.assertEqual(session.post.call_args.args[0], vs.BASE_URL + "/v1/audio/speech")
            self.assertFalse(session.trust_env)
            self.assertEqual(session.get.call_args.kwargs["timeout"], (1, 3))
            self.assertEqual(session.post.call_args.kwargs["timeout"], (1, 180))
            self.assertTrue(vs.fetch_speech("Hello.", folder)[2])
            self.assertEqual(session.post.call_count, 1)

    def test_missing_model_or_consent_never_synthesizes(self):
        for installed, accepted in [(False, True), (True, False)]:
            vs.reset_session()
            session = self.session(installed, accepted)
            with tempfile.TemporaryDirectory() as folder, patch.object(vs.requests, "Session") as client:
                client.return_value.__enter__.return_value = session
                with self.assertRaises(RuntimeError):
                    vs.fetch_speech("Hello.", folder)
                session.post.assert_not_called()
                self.assertIsNone(vs.fetch_speech("Another line.", folder))
                session.get.assert_called_once()

    def test_invalid_audio_is_not_cached(self):
        session = self.session()
        session.post.return_value.content = b"not audio"
        with tempfile.TemporaryDirectory() as folder, patch.object(vs.requests, "Session") as client:
            client.return_value.__enter__.return_value = session
            with self.assertRaises((wave.Error, EOFError)):
                vs.fetch_speech("Hello.", folder)
            self.assertEqual(os.listdir(folder), [])
