"""iPhone bridge checks. No Keychain, no iCloud, no macOS."""
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest import mock

import commands
from commands import bridge

SECRET = "bridge-test-secret"
NOW = 1_700_000_000


def _sign(cmd, ts, nonce, secret=SECRET):
    payload = f"{cmd}|{ts}|{nonce}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


class TestBridgeValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outbox = os.path.join(self.tmp.name, "outbox")
        self.nonce_log = os.path.join(self.tmp.name, "nonces.json")
        os.makedirs(self.outbox)
        patches = [
            mock.patch.object(bridge, "BRIDGE_OUTBOX", self.outbox),
            mock.patch.object(bridge, "NONCE_LOG", self.nonce_log),
            mock.patch.object(bridge, "_bridge_secret", return_value=SECRET),
            mock.patch.object(bridge.time, "time", return_value=NOW),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _process(self, cmd, nonce, ts=NOW, sig=None, name="cmd.json"):
        if sig is None:
            sig = _sign(cmd, ts, nonce)
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cmd": cmd, "ts": ts, "nonce": nonce, "sig": sig}, handle)
        calls = []

        def run_text(text):
            calls.append(text)
            return "Handled on the Mac."

        bridge._process_bridge_file(path, run_text)
        return calls, path

    def _reply(self, nonce):
        with open(os.path.join(self.outbox, nonce + ".json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_forged_signature_is_rejected(self):
        calls, path = self._process("what time is it", "nonce1234", sig="0" * 64)
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("verify", reply["reply"].lower())

    def test_replayed_nonce_is_rejected(self):
        first, _path = self._process("what time is it", "nonce1234")
        self.assertEqual(first, ["what time is it"])
        self.assertTrue(self._reply("nonce1234")["ok"])
        second, path = self._process("what time is it", "nonce1234", name="again.json")
        self.assertEqual(second, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("already", reply["reply"].lower())

    def test_timestamp_outside_the_window_is_rejected(self):
        late = NOW - (commands.BRIDGE_MAX_AGE + 1)
        early = NOW + (commands.BRIDGE_MAX_AGE + 1)
        for nonce, ts in (("nonceold1", late), ("noncenew1", early)):
            calls, path = self._process("what time is it", nonce, ts=ts, name=nonce + ".json")
            self.assertEqual(calls, [], nonce)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"])
            self.assertIn("too old", reply["reply"].lower())

    def test_open_and_close_stay_off_the_phone(self):
        """Typing and app open/close are Mac commands. A signed file still does not run."""
        phrases = (
            ("close imessage", "closeim1", "app_quit"),
            ("close iMessage.", "closeim2", "app_quit"),
            ("quit messages", "quitmsg1", "app_quit"),
            ("open imessage", "openimsg", "app_open"),
            ("hide messages", "hidemsg1", "app_hide"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            self.assertIn("phone", self._reply(nonce)["reply"].lower())
        for key in ("app_open", "app_quit", "app_hide", "app_focus"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)

    def test_disallowed_command_is_rejected(self):
        phrases = (
            ("empty the trash", "nonce1234"),
            ("run shortcut Leaving for work", "nonce5678"),
            ("quit all the apps", "nonce9012"),
        )
        for phrase, nonce in phrases:
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"])
            self.assertIn("phone", reply["reply"].lower())

    def test_oversized_command_is_rejected(self):
        cmd = "a" * (commands.BRIDGE_MAX_CMD + 1)
        calls, path = self._process(cmd, "nonce1234")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        reply = self._reply("nonce1234")
        self.assertFalse(reply["ok"])
        self.assertIn("too long", reply["reply"].lower())
        # The boundary stays where it was: 2000 characters is not rejected for length.
        exact = "b" * commands.BRIDGE_MAX_CMD
        calls, _path = self._process(exact, "nonce5678", name="exact.json")
        self.assertEqual(calls, [])
        self.assertNotIn("too long", self._reply("nonce5678")["reply"].lower())

    def test_my_love_and_cynthia_messages_are_rejected(self):
        """My Love is a real local command and is still blocked on the bridge.

        Cynthia is not a separate messages path. That phrase is not allowlisted,
        so the bridge refuses it before run_text, the same as any other command
        that is not on BRIDGE_ALLOW.
        """
        love = "check my messages from My Love"
        self.assertEqual(commands.route_before_api(love), "info_messages")
        self.assertIsNone(commands.bridge_allowed(love))
        calls, path = self._process(love, "nonce1234")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("nonce1234")["reply"].lower())

        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))

        cynthia = "check my messages from Cynthia"
        self.assertIsNone(commands.route_before_api(cynthia))
        self.assertIsNone(commands.bridge_allowed(cynthia))
        calls, path = self._process(cynthia, "cynthia1", name="cynthia.json")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("cynthia1")["reply"].lower())

    def test_payday_check_is_allowlisted_individually_and_my_love_stays_blocked(self):
        """Each payday-check phrase is one named allowlist entry. My Love is not.

        BRIDGE_ALLOW has no wildcard and no category prefix. info_payday_check
        is listed by itself. info_messages is absent, and a signed My Love
        file still never reaches run_text.
        """
        self.assertIn("info_payday_check", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
            self.assertNotIn("?", item)
            self.assertFalse(item.endswith("*"))

        phrases = (
            ("what's due today", "duetoday1"),
            ("payday check", "paydaychk"),
            ("any reminders today", "reminders"),
        )
        for phrase, nonce in phrases:
            self.assertEqual(commands.route_before_api(phrase), "info_payday_check", phrase)
            self.assertEqual(commands.bridge_allowed(phrase), "info_payday_check", phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [phrase], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertTrue(reply["ok"], phrase)
            self.assertEqual(reply["reply"], "Handled on the Mac.")

        love = "check my messages from My Love"
        self.assertEqual(commands.route_before_api(love), "info_messages")
        self.assertIsNone(commands.bridge_allowed(love))
        calls, path = self._process(love, "lovecheck")
        self.assertEqual(calls, [])
        self.assertFalse(os.path.exists(path))
        self.assertIn("phone", self._reply("lovecheck")["reply"].lower())

    def test_shift_and_leave_are_allowlisted_individually(self):
        """Each new phrase is its own allowlist name. My Love and money stay off."""
        self.assertIn("shift_set", commands.BRIDGE_ALLOW)
        self.assertIn("shift_clear", commands.BRIDGE_ALLOW)
        self.assertIn("info_leave", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
            self.assertNotIn("?", item)

        phrases = (
            ("my shift Monday is 9:30 to 6:30 at Brea", "shiftmon1", "shift_set"),
            ("clear my shift Monday", "shiftclr1", "shift_clear"),
            ("when should I leave for work", "leavewrk1", "info_leave"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertEqual(commands.bridge_allowed(phrase), key, phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [phrase], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertTrue(reply["ok"], phrase)
            self.assertEqual(reply["reply"], "Handled on the Mac.")

        self.assertIsNone(commands.bridge_allowed("check my messages from My Love"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))
        self.assertIsNone(commands.bridge_allowed("confirm the transfer"))

    def test_clipboard_history_is_refused_on_the_bridge(self):
        """Clipboard commands are local. A signed file never runs them or copies the text out.

        The stand-in run_text would return the spoken history if it were called.
        The outbox reply is the phone refusal, and it does not contain the item.
        """
        marker = "MARKER-clipboard-body-not-for-icloud"
        commands.CLIPBOARD.clear_items()
        commands.CLIPBOARD.last_change = None
        commands.CLIPBOARD.paused = False

        def _reset():
            commands.CLIPBOARD.clear_items()
            commands.CLIPBOARD.last_change = None
            commands.CLIPBOARD.paused = False

        self.addCleanup(_reset)
        from commands.clipboard_history import Snapshot
        self.assertEqual(commands.CLIPBOARD.observe(Snapshot(1, marker)), "stored")
        phrases = (
            ("clipboard history", "cliphist1", "clipboard_history"),
            ("show me my clipboard history", "cliphist2", "clipboard_history"),
            ("paste item 2", "clipaste2", "clipboard_paste"),
            ("copy item 2", "clipcopy2", "clipboard_copy"),
            ("clear clipboard history", "clipclr01", "clipboard_clear"),
            ("pause clipboard history", "clipause1", "clipboard_pause"),
            ("resume clipboard history", "clipresum", "clipboard_resume"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
            calls, path = self._process_clipboard(phrase, nonce)
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower())
            self.assertNotIn(marker, reply["reply"])
            self.assertNotIn(marker, json.dumps(reply))

    def _process_clipboard(self, cmd, nonce, ts=NOW, name=None):
        """Like _process, but a mistaken allow would write the clipboard speech."""
        sig = _sign(cmd, ts, nonce)
        path = os.path.join(self.tmp.name, name or nonce + ".json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"cmd": cmd, "ts": ts, "nonce": nonce, "sig": sig}, handle)
        calls = []

        def run_text(text):
            calls.append(text)
            speech = commands.speak_clipboard_history()
            return getattr(speech, "text", "")

        bridge._process_bridge_file(path, run_text)
        return calls, path

    def test_zoe_mode_cannot_be_entered_or_left_from_the_phone(self):
        """Zoe mode keys are not on BRIDGE_ALLOW. A signed file never reaches run_text."""
        phrases = (
            ("zoe mode", "zoemode1", "zoe_mode_on"),
            ("kid mode", "kidmode1", "zoe_mode_on"),
            ("kid mode on", "kidon001", "zoe_mode_on"),
            ("turn on zoe mode", "turnonz1", "zoe_mode_on"),
            ("turn on kid mode", "turnonk1", "zoe_mode_on"),
            ("start zoe mode", "startzo1", "zoe_mode_on"),
            ("enter zoe mode", "enterzo1", "zoe_mode_on"),
            ("zoe mode on", "zoemode2", "zoe_mode_on"),
            ("exit zoe mode", "exitzom1", "zoe_mode_off"),
            ("leave zoe mode", "leavezo1", "zoe_mode_off"),
            ("turn off zoe mode", "offfzoe1", "zoe_mode_off"),
            ("turn off kid mode", "offkidm1", "zoe_mode_off"),
            ("kid mode off", "kidoff01", "zoe_mode_off"),
            ("stop zoe mode", "stopzoe1", "zoe_mode_off"),
            ("end zoe mode", "endzoe01", "zoe_mode_off"),
            ("leave kid mode", "leavekd1", "zoe_mode_off"),
            ("stop kid mode", "stopkid1", "zoe_mode_off"),
            ("joke", "jokephr1", "zoe_joke"),
            ("tell a joke", "tellajk1", "zoe_joke"),
            ("tell me a joke", "telljok1", "zoe_joke"),
            ("tell zoe a joke", "zoejoke1", "zoe_joke"),
            ("fun fact", "funfact1", "zoe_joke"),
            ("a fun fact", "afunfact", "zoe_joke"),
            ("tell me a fun fact", "funfact2", "zoe_joke"),
        )
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for key in ("zoe_mode_on", "zoe_mode_off", "zoe_joke"):
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower())

    def test_video_quick_actions_are_refused(self):
        """Video commands are Mac-only. A signed inbox file never reaches run_text."""
        from commands.video import VIDEO_ROUTE_KEYS

        bridge_src = open(os.path.join(os.path.dirname(__file__), "..", "commands", "bridge.py"), encoding="utf-8").read()
        for key in VIDEO_ROUTE_KEYS:
            self.assertNotIn(key, commands.BRIDGE_ALLOW, key)
            self.assertNotIn(key, bridge_src, key)
        phrases = (
            ("convert the recording to mp4", "video_mp4"),
            ("convert the last recording to mp4", "video_mp4"),
            ("convert this video to mp4", "video_mp4"),
            ("convert the video to an mp4", "video_mp4"),
            ("make the recording an mp4", "video_mp4"),
            ("please convert the last recording to mp4", "video_mp4"),
            ("trim the recording from 0:05 to 0:30", "video_trim"),
            ("trim the last recording from 0:05 to 0:30", "video_trim"),
            ("trim this video from 1:02:03 to 1:10:00", "video_trim"),
            ("trim the video from 5 to 30", "video_trim"),
            ("trim it from 0:05 to 0:30", "video_trim"),
            ("please trim the recording from 0:05 to 0:30", "video_trim"),
            ("compress the recording", "video_compress"),
            ("compress the last recording", "video_compress"),
            ("compress this video", "video_compress"),
            ("compress the video", "video_compress"),
            ("make the recording smaller", "video_compress"),
            ("make the last recording smaller", "video_compress"),
            ("extract the audio from the recording", "video_audio"),
            ("extract audio from the recording", "video_audio"),
            ("extract the audio from the last recording", "video_audio"),
            ("extract audio from the last recording", "video_audio"),
            ("extract the audio from this video", "video_audio"),
            ("save the audio from the recording", "video_audio"),
            ("save the audio from the last recording", "video_audio"),
            ("choose a video", "video_choose"),
            ("choose a video file", "video_choose"),
            ("pick a video", "video_choose"),
            ("pick a video file", "video_choose"),
            ("open a video file", "video_choose"),
            ("please choose a video", "video_choose"),
        )
        for index, (phrase, key) in enumerate(phrases):
            nonce = "vqa{0:05d}".format(index)
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path), phrase)
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower(), phrase)

    def test_morning_brief_memo_is_refused(self):
        """The memo stays on the Mac. brief me is still allowed on its own name."""
        self.assertIn("info_brief", commands.BRIDGE_ALLOW)
        self.assertNotIn("brief_play", commands.BRIDGE_ALLOW)
        self.assertNotIn("brief_stop", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        for item in commands.BRIDGE_ALLOW:
            self.assertNotIn("*", item)
            self.assertNotIn("?", item)

        self.assertEqual(commands.route_before_api("brief me"), "info_brief")
        self.assertEqual(commands.bridge_allowed("brief me"), "info_brief")
        calls, path = self._process("brief me", "briefme01")
        self.assertEqual(calls, ["brief me"])
        self.assertFalse(os.path.exists(path))
        self.assertTrue(self._reply("briefme01")["ok"])

        phrases = (
            ("play my brief", "memo0001", "brief_play"),
            ("play the brief", "memo0002", "brief_play"),
            ("play my morning brief", "memo0003", "brief_play"),
            ("play the morning brief", "memo0004", "brief_play"),
            ("play today's brief", "memo0005", "brief_play"),
            ("please play my brief", "memo0006", "brief_play"),
            ("play my brief please", "memo0007", "brief_play"),
            ("stop", "memo0008", "brief_stop"),
            ("please stop", "memo0009", "brief_stop"),
            ("stop the brief", "memo0010", "brief_stop"),
            ("stop my brief", "memo0011", "brief_stop"),
            ("stop playback", "memo0012", "brief_stop"),
            ("stop the playback", "memo0013", "brief_stop"),
            ("stop the memo", "memo0014", "brief_stop"),
        )
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path), phrase)
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower())

        self.assertIsNone(commands.bridge_allowed("check my messages from My Love"))
        self.assertIsNone(commands.bridge_allowed("move $600 to Zoe"))

    def test_apple_reminders_are_refused(self):
        """remind_add is a Mac command. A signed inbox file does not run it."""
        self.assertNotIn("remind_add", commands.BRIDGE_ALLOW)
        self.assertIsInstance(commands.BRIDGE_ALLOW, frozenset)
        phrases = (
            ("remind me to buy milk", "milkrem1"),
            ("remind me to call the dentist at 5 pm", "dentist5"),
            ("please remind me to walk the dog tonight", "dognight"),
            ("remind me to check the mail in 20 minutes", "mail20min"),
            ("remind me to water the plants on Friday", "plantsfr"),
            ("remind me to submit the report next Monday at noon", "reportmo"),
        )
        for phrase, nonce in phrases:
            self.assertEqual(commands.route_before_api(phrase), "remind_add", phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            self.assertNotIn("remind_add", commands.BRIDGE_ALLOW)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path))
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"])

    def test_leave_reminder_toggles_are_refused(self):
        """Leave-reminder toggles are Mac-only. info_leave stays allowlisted."""
        phrases = (
            ("turn on leave reminders", "leaveon01", "leave_reminders_on"),
            ("turn off leave reminders", "leaveoff1", "leave_reminders_off"),
            ("leave reminders on", "leaveon02", "leave_reminders_on"),
            ("leave reminders off", "leaveoff2", "leave_reminders_off"),
            ("enable leave reminders", "leaveon03", "leave_reminders_on"),
            ("disable leave reminders", "leaveoff3", "leave_reminders_off"),
            ("please turn on leave reminders", "leaveon04", "leave_reminders_on"),
            ("turn off leave reminders please", "leaveoff4", "leave_reminders_off"),
        )
        self.assertIn("info_leave", commands.BRIDGE_ALLOW)
        self.assertNotIn("leave_reminders_on", commands.BRIDGE_ALLOW)
        self.assertNotIn("leave_reminders_off", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        for phrase, nonce, key in phrases:
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
            self.assertNotIn(key, commands.BRIDGE_ALLOW, phrase)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
            calls, path = self._process(phrase, nonce, name=nonce + ".json")
            self.assertEqual(calls, [], phrase)
            self.assertFalse(os.path.exists(path), phrase)
            reply = self._reply(nonce)
            self.assertFalse(reply["ok"], phrase)
            self.assertIn("can't do that from your phone", reply["reply"].lower())
