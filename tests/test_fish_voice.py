"""Dramatic voice. Temp files, a fake Fish client, no network and no Keychain."""
import hashlib
import os
import tempfile
import unittest

import commands
from commands.fish_voice import (
    DEFAULT_CUE,
    DRAMA_MODEL,
    DRAMA_PLAN_NOTICE,
    FISH_MODEL,
    FISH_TTS_TIMEOUT,
    FISH_TTS_URL,
    cache_path,
    cache_token,
    reset_drama_session,
    strip_fish_cues,
    with_default_cue,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOICE_ID = "9a9cf47702da476aa4629e2506d4a857"
API_KEY = "fish-test-key-not-real"


class _Response(object):
    def __init__(self, status=200, content=b"RIFFfakewav"):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            error = RuntimeError("status {0}".format(self.status_code))
            error.response = self
            raise error


class _Client(object):
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({
            "url": url,
            "headers": dict(headers or {}),
            "json": dict(json or {}),
            "timeout": timeout,
        })
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class TestVoiceSetting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "voice-mode.txt")
        commands.set_voice_mode_path(self.path)
        self.addCleanup(commands.set_voice_mode_path, None)

    def test_it_is_off_until_someone_asks(self):
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(commands.dramatic_voice_enabled())
        self.assertEqual(commands.which_voice(), "I'm using the normal voice.")
        self.assertEqual(commands.use_normal_voice(), "You're already using the normal voice.")
        self.assertFalse(os.path.exists(self.path))

    def test_use_dramatic_voice_persists_and_use_normal_voice_clears_it(self):
        self.assertEqual(commands.use_dramatic_voice(), "Dramatic voice is on.")
        self.assertEqual(open(self.path, encoding="utf-8").read(), "dramatic\n")
        self.assertTrue(commands.dramatic_voice_enabled())
        self.assertEqual(commands.which_voice(), "I'm using the dramatic voice.")
        self.assertEqual(commands.use_dramatic_voice(), "You're already using the dramatic voice.")
        self.assertEqual(open(self.path, encoding="utf-8").read(), "dramatic\n")
        commands.set_voice_mode_path(self.path)
        self.assertTrue(commands.dramatic_voice_enabled())
        self.assertEqual(commands.use_normal_voice(), "Normal voice is on.")
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(commands.dramatic_voice_enabled())
        self.assertEqual(commands.which_voice(), "I'm using the normal voice.")

    def test_a_save_failure_does_not_claim_the_voice_changed(self):
        blocker = os.path.join(self.tmp.name, "not-a-directory")
        with open(blocker, "w", encoding="utf-8") as handle:
            handle.write("x")
        commands.set_voice_mode_path(os.path.join(blocker, "voice-mode.txt"))
        self.assertEqual(commands.use_dramatic_voice(), "I couldn't save the voice setting.")
        self.assertFalse(commands.dramatic_voice_enabled())

    def test_the_spoken_reply_has_no_cue_for_the_window_to_read_aloud(self):
        for line in (
            commands.use_dramatic_voice(),
            commands.use_normal_voice(),
            commands.which_voice(),
        ):
            self.assertNotIn("[", line)
            self.assertNotIn("<", line)


class TestRouting(unittest.TestCase):
    def test_typed_and_spoken_phrases_route_and_stay_off_the_bridge(self):
        phrases = {
            "use dramatic voice": "voice_dramatic",
            "Use dramatic voice.": "voice_dramatic",
            "use the dramatic voice": "voice_dramatic",
            "use a dramatic voice": "voice_dramatic",
            "please use dramatic voice": "voice_dramatic",
            "use dramatic voice please": "voice_dramatic",
            "hey jev, use dramatic voice": "voice_dramatic",
            "hey jev use dramatic voice": "voice_dramatic",
            "please hey jev, use dramatic voice": "voice_dramatic",
            "use normal voice": "voice_normal",
            "use the normal voice": "voice_normal",
            "hey jev, use normal voice": "voice_normal",
            "please use normal voice": "voice_normal",
            "which voice are you using": "voice_which",
            "which voice are you using?": "voice_which",
            "what voice are you using": "voice_which",
            "which voice are you using right now": "voice_which",
            "hey jev, which voice are you using": "voice_which",
            "please what voice are you using now": "voice_which",
        }
        self.assertEqual(len(commands.BRIDGE_ALLOW), 30)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for phrase, key in phrases.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
            self.assertIn(key, commands.ZOE_ALLOW, phrase)
        self.assertIsNone(commands.route_before_api("use dramatic voice and open notes"))
        self.assertEqual(commands.route_before_api("turn on voice control"), "access_voice_control")
        self.assertEqual(commands.route_before_api("voiceover"), "voiceover_on")
        self.assertNotEqual(commands.route_before_api("use voice control"), "voice_dramatic")

    def test_siri_keeps_the_keychain_read_and_the_same_voice_id(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('FISH_KEY = get_secret("FISH_AUDIO_API_KEY")', source)
        self.assertIn('VOICE_ID = "9a9cf47702da476aa4629e2506d4a857"', source)
        for key in ("voice_dramatic", "voice_normal", "voice_which"):
            self.assertIn('"{0}"'.format(key), source)
        self.assertIn("use_dramatic_voice", source)
        self.assertIn("use_normal_voice", source)
        self.assertIn("which_voice", source)
        fetch = source.split("def fetch_tts", 1)[1].split("\ndef speak", 1)[0]
        self.assertIn("synthesize_speech", fetch)
        self.assertIn("api_key=FISH_KEY", fetch)
        self.assertIn("voice_id=VOICE_ID", fetch)
        self.assertIn("dramatic_voice_enabled", fetch)
        self.assertIn("post=requests.post", fetch)
        speak = source.split("def speak(text):", 1)[1].split("\ndef all_scripted_lines", 1)[0]
        self.assertIn("play_fish_reply", speak)
        self.assertIn("afplay", speak)
        self.assertNotIn("reference_id", fetch)
        self.assertNotIn('"model"', fetch)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        secrets = open(os.path.join(ROOT, "secrets_store.py"), encoding="utf-8").read()
        helper = open(os.path.join(ROOT, "commands", "fish_voice.py"), encoding="utf-8").read()
        for needle in ("voice_dramatic", "voice_normal", "voice_which", "drama-3-preview"):
            self.assertNotIn(needle, bridge)
            self.assertNotIn(needle, secrets)
        self.assertNotIn("import requests", helper)
        self.assertNotIn("urllib", helper)
        self.assertNotIn("secrets_store", helper)


class TestCues(unittest.TestCase):
    def test_the_default_cue_is_the_short_drama_direction(self):
        self.assertEqual(DEFAULT_CUE, "[warm and relaxed]")
        self.assertEqual(DRAMA_MODEL, "drama-3-preview")
        self.assertEqual(FISH_MODEL, "s2.1-pro-free")
        self.assertEqual(with_default_cue("[cheerful] Here you go."),
                         "[warm and relaxed] [cheerful] Here you go.")
        self.assertEqual(with_default_cue("[warm and relaxed] Already set."),
                         "[warm and relaxed] Already set.")
        self.assertEqual(with_default_cue("[Warm and relaxed] Already set."),
                         "[Warm and relaxed] Already set.")

    def test_cues_come_out_before_a_fallback_could_speak_them(self):
        samples = {
            "[warm and relaxed] It's been a while.": "It's been a while.",
            "Alright, [sigh] let's try again.": "Alright, let's try again.",
            "I'm fine. Really. <whisper>Go on without me.</whisper>":
                "I'm fine. Really. Go on without me.",
            "[cheerful] Here you go.": "Here you go.",
            "[warm and relaxed] [cheerful] <whisper>Hi</whisper> there.": "Hi there.",
            "<emphasis>really</emphasis> important": "really important",
            "It is warm and relaxed today.": "It is warm and relaxed today.",
            "[sigh]": "",
        }
        for raw, spoken in samples.items():
            self.assertEqual(strip_fish_cues(raw), spoken, raw)
            self.assertNotIn("[", strip_fish_cues(raw))
            self.assertNotIn("whisper>", strip_fish_cues(raw).lower())

    def test_the_normal_cache_key_stays_voice_and_text(self):
        text = "[cheerful] Here you go."
        token = cache_token(VOICE_ID, FISH_MODEL, text)
        self.assertEqual(token, "{0}|{1}".format(VOICE_ID, text))
        digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
        self.assertTrue(cache_path("/tmp/tts", VOICE_ID, FISH_MODEL, text).endswith(digest + ".wav"))
        drama = cache_token(VOICE_ID, DRAMA_MODEL, with_default_cue(text))
        self.assertIn(DRAMA_MODEL, drama)
        self.assertNotEqual(drama, token)


class TestSynthesize(unittest.TestCase):
    def setUp(self):
        reset_drama_session()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(reset_drama_session)
        self.logs = []

    def _speak(self, text, steps, dramatic):
        client = _Client(steps)
        result = commands.synthesize_speech(
            text,
            post=client,
            api_key=API_KEY,
            voice_id=VOICE_ID,
            dramatic=dramatic,
            cache_dir=self.tmp.name,
            log=self.logs.append,
        )
        return result, client

    def test_the_normal_voice_keeps_the_current_model_and_the_tags(self):
        text = "[cheerful] Here you go."
        result, client = self._speak(text, [_Response(content=b"normal-wav")], False)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["url"], FISH_TTS_URL)
        self.assertEqual(call["timeout"], FISH_TTS_TIMEOUT)
        self.assertEqual(call["timeout"], 60)
        self.assertEqual(call["headers"]["model"], FISH_MODEL)
        self.assertEqual(call["headers"]["Authorization"], "Bearer {0}".format(API_KEY))
        self.assertEqual(call["headers"]["Content-Type"], "application/json")
        self.assertEqual(call["json"]["text"], text)
        self.assertEqual(call["json"]["reference_id"], VOICE_ID)
        self.assertEqual(call["json"]["format"], "wav")
        self.assertNotIn("model", call["json"])
        self.assertFalse(result.fell_back)
        self.assertEqual(result.model, FISH_MODEL)
        self.assertEqual(open(result.path, "rb").read(), b"normal-wav")
        self.assertEqual(self.logs, [])
        again, client_again = self._speak(text, [], False)
        self.assertEqual(client_again.calls, [])
        self.assertTrue(again.cached)
        self.assertEqual(again.path, result.path)

    def test_dramatic_voice_sends_drama_3_with_the_same_reference_id(self):
        text = "[cheerful] I'm fine. Really. <whisper>Go on without me.</whisper>"
        result, client = self._speak(text, [_Response(content=b"drama-wav")], True)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        self.assertEqual(call["headers"]["model"], "drama-3-preview")
        self.assertEqual(call["headers"]["Authorization"], "Bearer {0}".format(API_KEY))
        self.assertEqual(call["json"]["reference_id"], VOICE_ID)
        self.assertEqual(call["json"]["format"], "wav")
        self.assertTrue(call["json"]["text"].startswith("[warm and relaxed] "))
        self.assertIn("[cheerful]", call["json"]["text"])
        self.assertIn("<whisper>Go on without me.</whisper>", call["json"]["text"])
        self.assertEqual(result.model, DRAMA_MODEL)
        self.assertFalse(result.fell_back)
        self.assertEqual(self.logs, [])
        self.assertEqual(open(result.path, "rb").read(), b"drama-wav")

    def test_a_normal_cache_is_not_reused_as_the_dramatic_voice(self):
        text = "Opening it up."
        normal, _client = self._speak(text, [_Response(content=b"normal-wav")], False)
        dramatic, client = self._speak(text, [_Response(content=b"drama-wav")], True)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL)
        self.assertNotEqual(dramatic.path, normal.path)
        self.assertEqual(open(dramatic.path, "rb").read(), b"drama-wav")

    def test_drama_errors_fall_back_without_cues_and_log_one_line(self):
        text = "[cheerful] I'm fine. Really. <whisper>Go on without me.</whisper>"
        errors = (
            TimeoutError("timed out"),
            RuntimeError("status 503"),
            _Response(status=500, content=b"nope"),
            _Response(status=200, content=b""),
        )
        # The 500 response raises from raise_for_status. Give it a status.
        errors[1].response = _Response(status=503)
        for exc in errors:
            self.logs = []
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            client = _Client([exc, _Response(content=b"fallback-wav")])
            result = commands.synthesize_speech(
                text,
                post=client,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=folder.name,
                log=self.logs.append,
            )
            self.assertIsNotNone(result, type(exc).__name__)
            self.assertTrue(result.fell_back, type(exc).__name__)
            self.assertEqual(result.model, FISH_MODEL)
            self.assertEqual(len(client.calls), 2, type(exc).__name__)
            first, second = client.calls
            self.assertEqual(first["headers"]["model"], DRAMA_MODEL)
            self.assertEqual(second["headers"]["model"], FISH_MODEL)
            self.assertEqual(second["json"]["reference_id"], VOICE_ID)
            self.assertEqual(second["timeout"], 60)
            self.assertEqual(second["json"]["text"], "I'm fine. Really. Go on without me.")
            self.assertNotIn("[", second["json"]["text"])
            self.assertNotIn("whisper", second["json"]["text"].lower())
            self.assertNotIn("warm and relaxed", second["json"]["text"])
            self.assertEqual(len(self.logs), 1, self.logs)
            self.assertIn("drama-3-preview", self.logs[0])
            self.assertIn("s2.1-pro-free", self.logs[0])
            self.assertNotIn(API_KEY, self.logs[0])
            self.assertNotIn("warm and relaxed", self.logs[0])
            self.assertEqual(open(result.path, "rb").read(), b"fallback-wav")

    def test_a_cached_normal_line_is_used_when_drama_fails(self):
        text = "Opening it up."
        normal, _client = self._speak(text, [_Response(content=b"cached-normal")], False)
        self.logs = []
        result, client = self._speak(text, [TimeoutError("timed out")], True)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL)
        self.assertTrue(result.fell_back)
        self.assertTrue(result.cached)
        self.assertEqual(result.path, normal.path)
        self.assertEqual(open(result.path, "rb").read(), b"cached-normal")
        self.assertEqual(len(self.logs), 1)

    def test_a_cue_only_line_is_not_spoken_when_drama_fails(self):
        result, client = self._speak("[sigh]", [TimeoutError("timed out")], True)
        self.assertIsNone(result)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(self.logs), 1)
        self.assertIn("no words left to speak", self.logs[0])
        self.assertNotIn(API_KEY, self.logs[0])

    def test_both_models_failing_returns_nothing_and_does_not_raise(self):
        result, client = self._speak(
            "[cheerful] Hello.",
            [TimeoutError("timed out"), _Response(status=401, content=b"no")],
            True,
        )
        self.assertIsNone(result)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client.calls[1]["json"]["text"], "Hello.")
        self.assertEqual(len(self.logs), 1)
        self.assertIn("drama-3-preview", self.logs[0])
        self.assertIn("s2.1-pro-free", self.logs[0])
        self.assertIn("also failed", self.logs[0])
        self.assertNotIn(API_KEY, self.logs[0])

    def test_the_normal_model_failing_does_not_raise(self):
        result, client = self._speak("Hello.", [TimeoutError("timed out")], False)
        self.assertIsNone(result)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["headers"]["model"], FISH_MODEL)
        self.assertEqual(len(self.logs), 1)
        self.assertIn("s2.1-pro-free", self.logs[0])
        self.assertNotIn("drama-3-preview", self.logs[0])

    def test_a_plan_denial_disables_drama_for_the_rest_of_the_session(self):
        notice = "Dramatic voice isn't available on your Fish Audio plan right now, so I'm using my normal voice."
        self.assertEqual(DRAMA_PLAN_NOTICE, notice)
        for status in (402, 401, 403):
            reset_drama_session()
            self.logs = []
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            voice = os.path.join(folder.name, "voice-mode.txt")
            commands.set_voice_mode_path(voice)
            self.addCleanup(commands.set_voice_mode_path, None)
            self.assertEqual(commands.use_dramatic_voice(), "Dramatic voice is on.")
            client = _Client([_Response(status=status), _Response(content=b"fallback-wav")])
            result = commands.synthesize_speech(
                "[cheerful] First line.",
                post=client,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=os.path.join(folder.name, "cache"),
                log=self.logs.append,
            )
            self.assertIsNotNone(result, status)
            self.assertTrue(result.fell_back, status)
            self.assertEqual(result.model, FISH_MODEL, status)
            self.assertEqual(len(client.calls), 2, status)
            self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL, status)
            self.assertEqual(client.calls[1]["headers"]["model"], FISH_MODEL, status)
            self.assertEqual(client.calls[1]["json"]["text"], "First line.", status)
            self.assertNotIn("[", client.calls[1]["json"]["text"])
            self.assertNotIn("cheerful", client.calls[1]["json"]["text"])
            self.assertNotIn(notice, client.calls[1]["json"]["text"])
            self.assertEqual(commands.claim_drama_plan_notice(), notice)
            self.assertEqual(commands.claim_drama_plan_notice(), "")
            self.assertEqual(len(self.logs), 1, self.logs)
            self.assertIn("for the rest of this session", self.logs[0])
            self.assertIn(str(status), self.logs[0])
            self.assertIn(DRAMA_MODEL, self.logs[0])
            self.assertIn(FISH_MODEL, self.logs[0])
            self.assertNotIn(API_KEY, self.logs[0])
            self.assertNotIn(notice, self.logs[0])
            self.assertEqual(open(voice, encoding="utf-8").read(), "dramatic\n")
            self.assertTrue(commands.dramatic_voice_enabled())
            self.assertEqual(commands.which_voice(), "I'm using the dramatic voice.")

            client2 = _Client([_Response(content=b"second-wav")])
            result2 = commands.synthesize_speech(
                "[sighing] Second line.",
                post=client2,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=os.path.join(folder.name, "cache"),
                log=self.logs.append,
            )
            self.assertEqual(len(client2.calls), 1, status)
            self.assertEqual(client2.calls[0]["headers"]["model"], FISH_MODEL, status)
            self.assertEqual(client2.calls[0]["json"]["text"], "Second line.", status)
            self.assertNotIn(notice, client2.calls[0]["json"]["text"])
            self.assertNotIn("[", client2.calls[0]["json"]["text"])
            self.assertTrue(result2.fell_back, status)
            self.assertEqual(result2.model, FISH_MODEL, status)
            self.assertEqual(open(result2.path, "rb").read(), b"second-wav")
            self.assertEqual(len(self.logs), 1, self.logs)
            self.assertEqual(open(voice, encoding="utf-8").read(), "dramatic\n")

    def test_timeouts_and_server_errors_still_try_drama_on_the_next_line(self):
        for exc in (TimeoutError("timed out"), _Response(status=503), _Response(status=500)):
            reset_drama_session()
            self.logs = []
            folder = tempfile.TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            client = _Client([exc, _Response(content=b"fallback-wav")])
            result = commands.synthesize_speech(
                "[cheerful] Hello.",
                post=client,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=folder.name,
                log=self.logs.append,
            )
            self.assertIsNotNone(result, type(exc).__name__)
            self.assertEqual(len(client.calls), 2, type(exc).__name__)
            self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL)
            self.assertEqual(client.calls[1]["headers"]["model"], FISH_MODEL)
            self.assertEqual(client.calls[1]["json"]["text"], "Hello.")
            self.assertNotIn(DRAMA_PLAN_NOTICE, client.calls[1]["json"]["text"])
            self.assertEqual(len(self.logs), 1, self.logs)
            self.assertNotIn("for the rest of this session", self.logs[0])
            client2 = _Client([_Response(content=b"drama-wav")])
            result2 = commands.synthesize_speech(
                "Next line.",
                post=client2,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=folder.name,
                log=self.logs.append,
            )
            self.assertEqual(len(client2.calls), 1, type(exc).__name__)
            self.assertEqual(client2.calls[0]["headers"]["model"], DRAMA_MODEL)
            self.assertFalse(result2.fell_back)
            self.assertEqual(result2.model, DRAMA_MODEL)

    def _fetch(self, client, cache_dir):
        def fetch(line):
            result = commands.synthesize_speech(
                line,
                post=client,
                api_key=API_KEY,
                voice_id=VOICE_ID,
                dramatic=True,
                cache_dir=cache_dir,
                log=self.logs.append,
            )
            if result is None:
                return None, 0
            return result.path, result.ms
        return fetch

    def test_playback_says_the_plan_notice_once_before_the_reply(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        client = _Client([
            _Response(status=402),
            _Response(content=b"reply-wav"),
            _Response(content=b"notice-wav"),
        ])
        played = []
        commands.play_fish_reply(
            "[cheerful] Hello.",
            self._fetch(client, folder.name),
            played.append,
        )
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL)
        self.assertEqual(client.calls[1]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client.calls[1]["json"]["text"], "Hello.")
        self.assertEqual(client.calls[2]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client.calls[2]["json"]["text"], DRAMA_PLAN_NOTICE)
        self.assertEqual([open(path, "rb").read() for path in played], [b"notice-wav", b"reply-wav"])
        self.assertEqual(len(self.logs), 1, self.logs)
        self.assertIn("402", self.logs[0])
        self.assertIn("for the rest of this session", self.logs[0])
        self.assertNotIn(DRAMA_PLAN_NOTICE, self.logs[0])
        self.assertNotIn(API_KEY, self.logs[0])

        client2 = _Client([_Response(content=b"second-wav")])
        played2 = []
        commands.play_fish_reply("Next line.", self._fetch(client2, folder.name), played2.append)
        self.assertEqual(len(client2.calls), 1)
        self.assertEqual(client2.calls[0]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client2.calls[0]["json"]["text"], "Next line.")
        self.assertEqual([open(path, "rb").read() for path in played2], [b"second-wav"])
        self.assertEqual(len(self.logs), 1, self.logs)

    def test_a_failed_reply_still_says_the_plan_notice_once(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        client = _Client([
            _Response(status=402),
            _Response(status=500),
            _Response(content=b"notice-wav"),
        ])
        played = []
        commands.play_fish_reply(
            "[cheerful] Hello.",
            self._fetch(client, folder.name),
            played.append,
        )
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[0]["headers"]["model"], DRAMA_MODEL)
        self.assertEqual(client.calls[1]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client.calls[1]["json"]["text"], "Hello.")
        self.assertEqual(client.calls[2]["json"]["text"], DRAMA_PLAN_NOTICE)
        self.assertEqual([open(path, "rb").read() for path in played], [b"notice-wav"])
        self.assertEqual(len(self.logs), 1, self.logs)
        self.assertIn("also failed", self.logs[0])
        self.assertIn("for the rest of this session", self.logs[0])
        self.assertNotIn(API_KEY, self.logs[0])

        client2 = _Client([_Response(content=b"still-wav")])
        played2 = []
        commands.play_fish_reply("Still here.", self._fetch(client2, folder.name), played2.append)
        self.assertEqual(len(client2.calls), 1)
        self.assertEqual(client2.calls[0]["headers"]["model"], FISH_MODEL)
        self.assertEqual(client2.calls[0]["json"]["text"], "Still here.")
        self.assertEqual([open(path, "rb").read() for path in played2], [b"still-wav"])
        self.assertEqual(len(self.logs), 1, self.logs)

    def test_a_missed_notice_is_said_on_the_next_reply(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        client = _Client([
            _Response(status=402),
            _Response(content=b"reply-wav"),
            _Response(status=500),
            _Response(content=b"next-wav"),
            _Response(content=b"notice-wav"),
        ])
        played = []
        commands.play_fish_reply("[cheerful] Hello.", self._fetch(client, folder.name), played.append)
        self.assertEqual([open(path, "rb").read() for path in played], [b"reply-wav"])
        played2 = []
        commands.play_fish_reply("Next line.", self._fetch(client, folder.name), played2.append)
        self.assertEqual(
            [open(path, "rb").read() for path in played2],
            [b"notice-wav", b"next-wav"],
        )
        self.assertEqual(client.calls[-1]["json"]["text"], DRAMA_PLAN_NOTICE)
        self.assertEqual(client.calls[-1]["headers"]["model"], FISH_MODEL)

    def test_a_normal_voice_402_does_not_disable_drama(self):
        result, client = self._speak("Hello.", [_Response(status=402)], False)
        self.assertIsNone(result)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["headers"]["model"], FISH_MODEL)
        result2, client2 = self._speak("Hello there.", [_Response(content=b"drama-wav")], True)
        self.assertEqual(len(client2.calls), 1)
        self.assertEqual(client2.calls[0]["headers"]["model"], DRAMA_MODEL)
        self.assertFalse(result2.fell_back)
        self.assertEqual(result2.model, DRAMA_MODEL)
