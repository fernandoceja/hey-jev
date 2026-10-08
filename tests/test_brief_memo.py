"""Morning brief voice memo. Temp files, a fake afplay, no Mac and no network."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

import commands
from commands.brief_memo import MemoPlayer


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLAY_PHRASES = (
    "play my brief",
    "play the brief",
    "play my morning brief",
    "play the morning brief",
    "play today's brief",
    "please play my brief",
    "play my brief please",
)
STOP_PHRASES = (
    "stop",
    "stop.",
    "please stop",
    "stop please",
    "stop the brief",
    "stop my brief",
    "stop playback",
    "stop the playback",
    "stop the memo",
)


class _Proc(object):
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15


def _player():
    calls = []
    procs = []

    def spawn(path):
        calls.append(commands.afplay_command(path))
        proc = _Proc()
        procs.append(proc)
        return proc

    return MemoPlayer(spawn=spawn), calls, procs


class TestBriefMemo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = os.path.join(self.tmp.name, "Daily Brief")
        self.state = os.path.join(self.tmp.name, "brief-memo.json")
        os.makedirs(self.folder)
        self.player, self.calls, self.procs = _player()
        self.spoken = []

    def _touch(self, name, when, folder=None):
        path = os.path.join(folder or self.folder, name)
        with open(path, "wb") as handle:
            handle.write(b"memo")
        stamp = when.timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def _run(self, now, **kwargs):
        options = {
            "now": now,
            "folder": self.folder,
            "state_path": self.state,
            "player": self.player,
            "speaker": self.spoken.append,
            "enabled": True,
            "when": datetime.strptime("07:10", "%H:%M").time(),
            "retries": 2,
            "window_minutes": 20,
        }
        options.update(kwargs)
        return commands.run_scheduled_brief(**options)

    def _saved(self):
        with open(self.state, encoding="utf-8") as handle:
            return json.load(handle)

    def test_newest_audio_file_wins_and_other_files_do_not(self):
        day = datetime(2026, 10, 8, 7, 0)
        early = self._touch("early.mp3", day)
        self._touch("notes.txt", day + timedelta(hours=4))
        self._touch("voice.wav", day + timedelta(hours=3))
        later = self._touch("later.m4a", day + timedelta(hours=1))
        newest = self._touch("newest.MP3", day + timedelta(hours=2))
        nested = os.path.join(self.folder, "nested")
        os.makedirs(nested)
        self._touch("hidden.mp3", day + timedelta(hours=5), folder=nested)
        same = day + timedelta(hours=2)
        os.utime(newest, (same.timestamp(), same.timestamp()))
        tied_old = self._touch("alpha.mp3", same)
        tied_new = self._touch("zeta.mp3", same)
        found = commands.list_memos(self.folder)
        self.assertIsNotNone(found)
        names = [item[1] for item in found]
        self.assertNotIn("notes.txt", names)
        self.assertNotIn("voice.wav", names)
        self.assertNotIn("hidden.mp3", names)
        self.assertEqual(found[-1][2], tied_new)
        self.assertIn(early, [item[2] for item in found])
        self.assertIn(later, [item[2] for item in found])
        self.assertIn(tied_old, [item[2] for item in found])
        today = [item for item in found if item[3] == day.date()]
        self.assertEqual(today[-1][2], tied_new)

    def test_scheduled_play_uses_todays_newest_file_and_afplay(self):
        yesterday = self._touch("yesterday.mp3", datetime(2026, 10, 7, 9, 0))
        older_today = self._touch("older.mp3", datetime(2026, 10, 8, 6, 0))
        today = self._touch("today.m4a", datetime(2026, 10, 8, 7, 5))
        job = self._run(datetime(2026, 10, 8, 7, 10))
        self.assertEqual(job["action"], "play")
        self.assertEqual(job["path"], today)
        self.assertNotEqual(job["path"], yesterday)
        self.assertNotEqual(job["path"], older_today)
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.calls, [["/usr/bin/afplay", today]])
        self.assertEqual(len(self.calls[0]), 2)
        self.assertNotIn("http", self.calls[0][1])
        saved = self._saved()
        self.assertEqual(saved["date"], "2026-10-08")
        self.assertTrue(saved["played"])
        self.assertFalse(saved["gave_up"])

    def test_an_older_memo_is_not_the_morning_play(self):
        self._touch("old.mp3", datetime(2026, 10, 7, 21, 0))
        job = self._run(datetime(2026, 10, 8, 7, 10))
        self.assertEqual(job["line"], commands.NOT_READY_LINE)
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])
        self.assertEqual(self.calls, [])
        self.assertFalse(self._saved()["played"])

    def test_a_restart_does_not_replay(self):
        path = self._touch("today.mp3", datetime(2026, 10, 8, 7, 1))
        first = self._run(datetime(2026, 10, 8, 7, 10))
        self.assertEqual(first["path"], path)
        again_player, again_calls, _procs = _player()
        second = commands.run_scheduled_brief(
            now=datetime(2026, 10, 8, 7, 12),
            folder=self.folder,
            state_path=self.state,
            player=again_player,
            speaker=self.spoken.append,
            enabled=True,
            when=datetime.strptime("07:10", "%H:%M").time(),
            retries=2,
            window_minutes=20,
        )
        self.assertIsNone(second)
        self.assertEqual(again_calls, [])
        self.assertEqual(len(self.calls), 1)

    def test_the_next_morning_can_play_again(self):
        self._touch("thu.mp3", datetime(2026, 10, 8, 7, 1))
        self._run(datetime(2026, 10, 8, 7, 10))
        friday = self._touch("fri.mp3", datetime(2026, 10, 9, 7, 2))
        job = self._run(datetime(2026, 10, 9, 7, 10))
        self.assertEqual(job["path"], friday)
        self.assertEqual(self.calls[-1], ["/usr/bin/afplay", friday])

    def test_missing_folder_is_quiet_after_the_not_ready_line(self):
        missing = os.path.join(self.tmp.name, "no-such-folder")
        job = self._run(datetime(2026, 10, 8, 7, 10), folder=missing)
        self.assertEqual(job["line"], commands.NOT_READY_LINE)
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])
        self.assertEqual(self.calls, [])
        self.assertIsNone(commands.list_memos(missing))
        not_a_dir = os.path.join(self.tmp.name, "file.txt")
        with open(not_a_dir, "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertIsNone(commands.list_memos(not_a_dir))

    def test_retries_then_gives_up_without_speaking_again(self):
        self.assertIsNone(self._run(datetime(2026, 10, 8, 7, 9)))
        self.assertEqual(self.spoken, [])
        self.assertFalse(os.path.exists(self.state))
        first = self._run(datetime(2026, 10, 8, 7, 10))
        self.assertEqual(first["action"], "not_ready")
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])
        self.assertIsNone(self._run(datetime(2026, 10, 8, 7, 15)))
        second = self._run(datetime(2026, 10, 8, 7, 20))
        self.assertEqual(second["action"], "retry")
        self.assertEqual(second["line"], "")
        third = self._run(datetime(2026, 10, 8, 7, 30))
        self.assertEqual(third["action"], "give_up")
        self.assertEqual(third["line"], "")
        self.assertTrue(third["state"]["gave_up"])
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])
        self.assertEqual(self.calls, [])
        self.assertIsNone(self._run(datetime(2026, 10, 8, 8, 0)))
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])

    def test_a_later_retry_plays_once_the_file_is_there(self):
        self._run(datetime(2026, 10, 8, 7, 10))
        path = self._touch("arrived.mp3", datetime(2026, 10, 8, 7, 18))
        job = self._run(datetime(2026, 10, 8, 7, 20))
        self.assertEqual(job["action"], "play")
        self.assertEqual(job["path"], path)
        self.assertEqual(self.calls, [["/usr/bin/afplay", path]])
        self.assertEqual(self.spoken, [commands.NOT_READY_LINE])
        self.assertIsNone(self._run(datetime(2026, 10, 8, 7, 30)))
        self.assertEqual(len(self.calls), 1)

    def test_after_the_window_it_gives_up_quietly(self):
        job = self._run(datetime(2026, 10, 8, 9, 0))
        self.assertEqual(job["action"], "give_up")
        self.assertEqual(job["line"], "")
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.calls, [])
        self.assertTrue(self._saved()["gave_up"])
        self.assertIsNone(self._run(datetime(2026, 10, 8, 9, 5)))

    def test_the_enable_toggle_skips_the_morning_play(self):
        path = self._touch("today.mp3", datetime(2026, 10, 8, 7, 1))
        job = self._run(datetime(2026, 10, 8, 7, 10), enabled=False)
        self.assertIsNone(job)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.spoken, [])
        self.assertFalse(os.path.exists(self.state))
        asked = commands.request_brief(self.folder, today=datetime(2026, 10, 8).date())
        self.assertIsInstance(asked, commands.BriefPlayback)
        self.assertEqual(asked.path, path)
        self.assertEqual(self.calls, [])

    def test_on_demand_plays_the_latest_and_says_an_older_date(self):
        missing = commands.request_brief(os.path.join(self.tmp.name, "absent"))
        self.assertEqual(missing, commands.MISSING_FOLDER_LINE)
        empty = commands.request_brief(self.folder, today=datetime(2026, 10, 8).date())
        self.assertEqual(empty, commands.EMPTY_FOLDER_LINE)
        old = self._touch("old.mp3", datetime(2025, 10, 7, 8, 0))
        asked = commands.request_brief(self.folder, today=datetime(2026, 10, 8).date())
        self.assertEqual(asked.path, old)
        self.assertIn("October 7th", asked.line)
        self.assertIn("2025", asked.line)
        self.assertNotIn("Playing your brief", asked.line)
        yesterday = self._touch("yesterday.mp3", datetime(2026, 10, 7, 8, 0))
        asked = commands.request_brief(self.folder, today=datetime(2026, 10, 8).date())
        self.assertEqual(asked.path, yesterday)
        self.assertEqual(asked.line, "Playing the brief from October 7th.")
        today = self._touch("today.mp3", datetime(2026, 10, 8, 7, 5))
        asked = commands.request_brief(self.folder, today=datetime(2026, 10, 8).date())
        self.assertEqual(asked.path, today)
        self.assertEqual(asked.line, "Playing your brief.")
        self.assertEqual(self.calls, [])

    def test_stop_terminates_afplay_and_a_second_play_replaces_the_first(self):
        first = self._touch("one.mp3", datetime(2026, 10, 8, 7, 1))
        second = self._touch("two.mp3", datetime(2026, 10, 8, 7, 2))
        self.assertTrue(commands.play_memo_file(first, player=self.player))
        self.assertTrue(commands.play_memo_file(second, player=self.player))
        self.assertTrue(self.procs[0].terminated)
        self.assertEqual(self.calls, [
            ["/usr/bin/afplay", first],
            ["/usr/bin/afplay", second],
        ])
        self.assertEqual(commands.stop_brief(player=self.player), "Stopped.")
        self.assertTrue(self.procs[1].terminated)
        self.assertEqual(commands.stop_brief(player=self.player), "Nothing is playing.")
        self.assertFalse(commands.play_memo_file(os.path.join(self.folder, "notes.txt"), player=self.player))
        self.assertEqual(len(self.calls), 2)

    def test_settings_defaults_and_env_overrides(self):
        settings = commands.brief_memo_settings({})
        self.assertTrue(settings["folder"].endswith(os.path.join("Documents", "Daily Brief")))
        self.assertTrue(settings["enabled"])
        self.assertEqual((settings["when"].hour, settings["when"].minute), (7, 10))
        self.assertEqual(settings["retries"], commands.BRIEF_MEMO_RETRIES)
        self.assertEqual(settings["window_minutes"], commands.BRIEF_MEMO_WINDOW_MINUTES)
        self.assertEqual(commands.BRIEF_MEMO_RETRIES, 2)
        self.assertEqual(commands.BRIEF_MEMO_WINDOW_MINUTES, 20)
        custom = commands.brief_memo_settings({
            "BRIEF_MEMO_DIR": "~/Documents/Other Brief",
            "BRIEF_MEMO_ENABLED": "off",
            "BRIEF_MEMO_TIME": "8:05",
            "BRIEF_MEMO_RETRIES": "1",
            "BRIEF_MEMO_WINDOW_MINUTES": "15",
        })
        self.assertTrue(custom["folder"].endswith(os.path.join("Documents", "Other Brief")))
        self.assertFalse(custom["enabled"])
        self.assertEqual((custom["when"].hour, custom["when"].minute), (8, 5))
        self.assertEqual(custom["retries"], 1)
        self.assertEqual(custom["window_minutes"], 15)
        self.assertFalse(commands.brief_memo_settings({"BRIEF_MEMO_ENABLED": "0"})["enabled"])
        self.assertFalse(commands.brief_memo_settings({"BRIEF_MEMO_ENABLED": "false"})["enabled"])
        self.assertFalse(commands.brief_memo_settings({"BRIEF_MEMO_ENABLED": "no"})["enabled"])
        bad = commands.brief_memo_settings({
            "BRIEF_MEMO_TIME": "nope",
            "BRIEF_MEMO_RETRIES": "lots",
            "BRIEF_MEMO_WINDOW_MINUTES": "-3",
            "BRIEF_MEMO_ENABLED": "1",
        })
        self.assertEqual((bad["when"].hour, bad["when"].minute), (7, 10))
        self.assertEqual(bad["retries"], 2)
        self.assertEqual(bad["window_minutes"], 20)
        self.assertTrue(bad["enabled"])

    def test_routes_do_not_steal_brief_me_or_other_stop_commands(self):
        for phrase in PLAY_PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "brief_play", phrase)
            self.assertNotIn("brief_play", commands.BRIDGE_ALLOW)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        for phrase in STOP_PHRASES:
            self.assertEqual(commands.route_before_api(phrase), "brief_stop", phrase)
            self.assertNotIn("brief_stop", commands.BRIDGE_ALLOW)
            self.assertIsNone(commands.bridge_allowed(phrase), phrase)
        self.assertEqual(commands.route_before_api("brief me"), "info_brief")
        self.assertEqual(commands.bridge_allowed("brief me"), "info_brief")
        self.assertIn("info_brief", commands.BRIDGE_ALLOW)
        self.assertNotIn("info_messages", commands.BRIDGE_ALLOW)
        untouched = {
            "play": "media_play",
            "play the music": "media_play",
            "pause": "media_pause",
            "stop recording": "record_stop",
            "stop the recording": "record_stop",
            "stop reading": "screen_stop",
            "stop the matrix": "matrix_off",
            "stop voiceover": "voiceover_off",
        }
        for phrase, key in untouched.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
        for phrase in (
            "stop the music",
            "play my briefs",
            "play my brief and open notes",
            "stop and open notes",
            "play brief",
        ):
            self.assertIsNone(commands.route_before_api(phrase), phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "brief_play", phrase)
            self.assertNotEqual(commands.route_before_api(phrase), "brief_stop", phrase)

    def test_siri_wires_the_commands_and_the_bridge_file_does_not(self):
        siri = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('"brief_play": lambda _arg, _text: commands.request_brief()', siri)
        self.assertIn('"brief_stop": lambda _arg, _text: commands.stop_brief()', siri)
        self.assertIn("start_brief_memo_thread", siri)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        self.assertNotIn("brief_play", bridge)
        self.assertNotIn("brief_stop", bridge)
        memo = open(os.path.join(ROOT, "commands", "brief_memo.py"), encoding="utf-8").read()
        self.assertNotIn("import socket", memo)
        self.assertNotIn("socket.socket", memo)
        self.assertNotIn(".listen(", memo)
        self.assertNotIn("BRIDGE_ALLOW", memo)
        self.assertNotIn("http://", memo)
        self.assertNotIn("https://", memo)
