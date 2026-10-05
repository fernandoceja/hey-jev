"""Round 2 routing and the Jev-folder shortcut check. No macOS, no network."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

import commands

TZ = ZoneInfo("America/Los_Angeles")
FOLDER = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
FOCUS = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
ZOE = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"
SEND = "DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD"
WORK = "EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE"
LEAVE = "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF"


def _line(name, ident):
    return f"{name} ({ident})"


ALL_SHORTCUTS = "\n".join([
    _line("Jev Focus On", FOCUS),
    _line("Zoe's Princess Academy", ZOE),
    _line("Leaving for work", LEAVE),
    _line("Send Money", SEND),
]) + "\n"
JEV_SHORTCUTS = "\n".join([
    _line("Jev Focus On", FOCUS),
    _line("Zoe's Princess Academy", ZOE),
    _line("Leaving for work", LEAVE),
]) + "\n"
FOLDERS = "\n".join([_line("Jev", FOLDER), _line("Work", WORK)]) + "\n"
FOLDERS_NO_JEV = _line("Work", WORK) + "\n"


def _at(year, month, day, hour=9, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _cp(args, stdout="", code=0):
    return subprocess.CompletedProcess(args, code, stdout, "")


class TestRouting(unittest.TestCase):
    def setUp(self):
        commands.clear_shortcut_cache()
        commands.clear_confirmation()

    def test_round2_phrases(self):
        expect = {
            "what can you do": "info_help",
            "help": "info_help",
            "what's the weather": "info_weather",
            "when's my next shift": "info_next_shift",
            "am I working this weekend": "info_weekend",
            "do I work this weekend": "info_weekend",
            "how long is my shift": "info_shift_length",
            "when do I start at Brea": "info_brea",
            "what time do I start at Brea": "info_brea",
            "my shift Monday is 9:30 to 6:30 at Brea": "shift_set",
            "my shift on Monday is 9:30 to 6:30 at Brea": "shift_set",
            "clear my shift Monday": "shift_clear",
            "clear my shift overrides": "shift_clear",
            "when should I leave for work": "info_leave",
            "what time should I leave for Brea": "info_leave",
            "what's due for school": "info_school",
            "what's due for UMGC": "info_school",
            "what's due this week for my class": "info_school",
            "what's due": "info_due",
            "what's due this week": "info_due",
            "what's due today": "info_payday_check",
            "payday check": "info_payday_check",
            "any reminders today": "info_payday_check",
            "when's rent due": "info_rent",
            "what bills are coming up": "info_bills",
            "how long until payday": "info_payday",
            "when is payday": "info_payday",
            "log 3 hours for grandma": "ihss_log",
            "log IHSS hours: 4 hours today": "ihss_log",
            "how many hours this pay period": "ihss_hours",
            "how many IHSS hours this pay period": "ihss_hours",
            "remind me to submit my timesheet": "ihss_remind",
            "play bohemian rhapsody on youtube": "youtube_play",
            "what's playing": "media_now",
            "what song is this": "media_now",
            "play": "media_play",
            "play the music": "media_play",
            "pause": "media_pause",
            "pause spotify": "media_pause",
            "next track": "media_next",
            "previous track": "media_previous",
            "volume up": "volume_up",
            "turn it down": "volume_down",
            "set the volume to 40": "volume_set",
            "set volume to 5": "volume_set",
            "mute": "volume_mute",
            "unmute": "volume_unmute",
            "brightness up": "brightness_up",
            "dimmer": "brightness_down",
            "what's my battery": "info_battery",
            "lock the screen": "system_lock",
            "take a screenshot": "screenshot",
            "empty the trash": "empty_trash",
            "show desktop": "show_desktop",
            "show the desktop": "show_desktop",
            "open downloads": "folder_open",
            "open the desktop folder": "folder_open",
            "open business email": "app_open",
            "open my phone": "app_open",
            "open settings": "app_open",
            "open numbers": "app_open",
            "open youtube": "app_open",
            "open books": "app_open",
            "open workjam": "site_open",
            "open bank of america": "site_open",
            "open shopify admin": "site_open",
            "open bookings": "site_open",
            "any new orders": "site_open",
            "continue chatgpt": "continue_chatgpt",
            "continue in chat gpt": "continue_chatgpt",
            "open princess academy": "zoe_academy",
            "start a 5 minute timer for zoe": "zoe_timer",
            "set a timer for zoe for 10 minutes": "zoe_timer",
            "run shortcut Leaving for work": "shortcut_run",
            "check my messages from My Love": "info_messages",
            "take a note: oat milk": "note_take",
            "what time is it": "info_time",
            "brief me": "info_brief",
        }
        for phrase, key in expect.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)

    def test_general_questions_stay_with_the_llm(self):
        untouched = [
            "who wrote hamlet",
            "what's the capital of france",
            "how long until summer",
            "what time is the super bowl",
            "what time is it in Tokyo",
            "what's the weather in paris",
            "help me write an email",
            "what can you do about my back",
            "what's due to change in the tax law",
            "when is payday for teachers in california",
            "move $600 to Zoe",
            "confirm the transfer",
            "am I working this weekend on a novel",
            "how long is my shift if traffic is bad",
            "open the pod bay doors",
            "play something from the wedding",
            "pause the movie",
            "remind me in 20 minutes to call mum",
            "quit all the apps",
            "screenshot the error message",
            "lock",
        ]
        for phrase in untouched:
            self.assertIsNone(commands.route_before_api(phrase), phrase)

    def test_bare_run_does_not_match_without_a_verified_folder(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return _cp(args, code=1)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            self.assertIsNone(commands.route_before_api("run a marathon next year"))
            self.assertEqual(commands.route_before_api("run shortcut Send Money"), "shortcut_run")
        self.assertTrue(calls)
        self.assertTrue(all(call[:2] == ["shortcuts", "list"] for call in calls))
        self.assertFalse(any(call[:2] == ["shortcuts", "run"] for call in calls))

    def test_empty_trash_needs_a_spoken_yes(self):
        self.assertIn("empty_trash", commands.CONFIRM)
        self.assertEqual(commands.route_before_api("empty the trash"), "empty_trash")
        self.assertIsNone(commands.bridge_allowed("empty the trash"))
        commands.arm_confirmation("empty_trash", None, "empty the trash", "empty_trash", {})
        self.assertEqual(commands.confirmation_status("yes"), "yes")
        action, _arg, source, _key, _fmt = commands.take_confirmation()
        self.assertEqual(action, "empty_trash")
        self.assertEqual(source, "empty the trash")

    def test_bridge_allows_reads_and_refuses_shortcuts(self):
        self.assertEqual(commands.bridge_allowed("how long until payday"), "info_payday")
        self.assertEqual(commands.bridge_allowed("what's due for school"), "info_school")
        self.assertIsNone(commands.bridge_allowed("run shortcut Leaving for work"))
        self.assertIsNone(commands.bridge_allowed("continue chatgpt"))

    def test_app_nicknames_do_not_collide(self):
        self.assertEqual(commands.known_app_name("business email"), "Zoho Mail - Desktop")
        self.assertEqual(commands.known_app_name("zoho"), "Zoho Mail - Desktop")
        self.assertEqual(commands.known_app_name("my phone"), "iPhone Mirroring")
        self.assertEqual(commands.known_app_name("mirroring"), "iPhone Mirroring")
        self.assertEqual(commands.known_app_name("phone"), "Phone")
        self.assertEqual(commands.known_app_name("numbers"), "Numbers Creator Studio")
        self.assertEqual(commands.known_app_name("budget app"), "Numbers Creator Studio")
        self.assertEqual(commands.known_app_name("settings"), "System Settings")
        self.assertEqual(commands.known_app_name("clean my mac"), "CleanMyMac_5")
        self.assertEqual(commands.known_app_name("youtube"), "YouTube")
        self.assertEqual(commands.known_app_name("youtube tv"), "YouTube TV")
        self.assertEqual(commands.known_app_name("books"), "Books")
        self.assertEqual(commands.known_app_name("mail"), "Mail")
        self.assertEqual(commands.known_app_name("music"), "Music")
        self.assertEqual(commands.known_app_name("messages"), "Messages")
        self.assertEqual(commands.known_app_name("news"), "News")
        self.assertEqual(commands.known_app_name("stocks"), "Stocks")
        self.assertEqual(commands.known_app_name("siri"), "Siri")
        self.assertEqual(commands.known_app_name("calculater"), "Calculator")
        self.assertIsNone(commands.resolve_site("books"))
        self.assertEqual(commands.resolve_site("bookings")["label"], "bookings")
        self.assertEqual(commands.resolve_site("ukg")["url"], "https://sso.prd.mykronos.com")
        self.assertEqual(
            commands.resolve_site("apple employee portal")["url"], "https://people.apple.com/")
        self.assertEqual(
            commands.resolve_site("ihss timesheet")["url"], "https://etimesheets.ihss.ca.gov/login")
        self.assertEqual(
            commands.resolve_site("orders")["url"],
            "https://admin.shopify.com/store/80-s-obsession-company/orders")
        self.assertEqual(
            commands.PRINCESS_ACADEMY_URL,
            "https://fernandoceja.github.io/Zoe-s-Princess-Academy/")
        self.assertEqual(commands.SHOPIFY_ORDERS_URL, commands.resolve_site("orders")["url"])
        for phrase in ("ukg", "apple employee portal", "orders", "ihss"):
            self.assertFalse(commands.resolve_site(phrase)["editable"], phrase)

    def test_sites_are_https_and_chrome_gets_an_argument_list(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((list(args), kwargs))
            return _cp(args)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            spoken = commands.open_site_from_text("open bank of america")
        self.assertIn("Bank of America", spoken)
        args, kwargs = calls[0]
        self.assertEqual(args[0], "open")
        self.assertEqual(args[1], "-a")
        self.assertEqual(args[2], "Google Chrome")
        self.assertTrue(args[3].startswith("https://secure.bankofamerica.com/"))
        self.assertNotEqual(kwargs.get("shell"), True)
        for entry in commands.SITE_CONFIG:
            self.assertTrue(entry["url"].startswith("https://"), entry["label"])
            self.assertNotIn(" ", entry["url"])

    def test_open_app_uses_open_a_and_reports_missing(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            return _cp(args, code=1, stdout="Unable to find application named Zoho")

        with mock.patch.object(commands.subprocess, "run", fake_run):
            spoken = commands.open_any_app(None, "open business email", {})
        self.assertEqual(calls[0], ["open", "-a", "Zoho Mail - Desktop"])
        self.assertIn("isn't installed", spoken)
        self.assertIn("Zoho Mail - Desktop", spoken)

    def test_youtube_search_is_not_a_shell_string(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append((list(args), kwargs))
            return _cp(args)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            spoken = commands.play_on_youtube("play rick astley & friends on youtube")
        args, kwargs = calls[0]
        self.assertEqual(args[:3], ["open", "-a", "Google Chrome"])
        self.assertIn("search_query=rick+astley", args[3])
        self.assertNotIn("&", args[3].split("search_query=", 1)[-1])
        self.assertNotEqual(kwargs.get("shell"), True)
        self.assertIn("rick astley", spoken)

    def test_music_target_prefers_apple_music(self):
        self.assertEqual(commands.music_target("play", False), "music")
        self.assertEqual(commands.music_target("pause the music", True), "music")
        self.assertIsNone(commands.music_target("pause spotify", False))
        self.assertEqual(commands.music_target("play spotify", True), "spotify")

    def test_volume_brightness_screenshot_and_reminder_are_argument_lists(self):
        """Brightness here is the key-code list, never DisplayServices or the CLI.

        On a Mac, change_brightness() loads DisplayServices and adds 10 percent
        before subprocess runs. A Homebrew brightness binary would be next.
        display=False and cli=False keep this on key codes 144 and 145 even
        when the platform is darwin and `brightness` is on PATH.
        """
        calls = []
        which_names = []
        real_which = shutil.which

        def fake_run(args, **kwargs):
            calls.append(list(args))
            if args[0] == "pmset":
                return _cp(args, stdout="Now drawing from 'Battery Power'\n -InternalBattery-0 81%; discharging;\n")
            return _cp(args)

        def which(name, *args, **kwargs):
            which_names.append(name)
            if name == "brightness":
                return "/opt/homebrew/bin/brightness"
            return real_which(name, *args, **kwargs)

        with mock.patch.object(sys, "platform", "darwin"), \
                mock.patch("shutil.which", which), \
                mock.patch.object(commands.subprocess, "run", fake_run):
            self.assertEqual(sys.platform, "darwin")
            self.assertIn("40", commands.set_mac_volume(None, "set the volume to 40"))
            self.assertEqual(commands.change_brightness("up", display=False, cli=False), "Brighter.")
            self.assertEqual(commands.change_brightness("down", display=False, cli=False), "Dimmer.")
            self.assertIn("81", commands.speak_battery())
            shot = commands.take_screenshot()
            reminded = commands.remind_timesheet()
            continued = commands.continue_chatgpt()
        self.assertIn("Desktop", shot)
        self.assertIn("Submit IHSS timesheet", reminded)
        self.assertIn("continue", continued)
        joined = [" ".join(call) for call in calls]
        self.assertTrue(any(call[:2] == ["osascript", "-e"] and "output volume 40" in call[2] for call in calls))
        self.assertTrue(any("key code 144" in " ".join(call) for call in calls))
        self.assertTrue(any("key code 145" in " ".join(call) for call in calls))
        self.assertTrue(any(call[0] == "screencapture" and "Desktop" in call[-1] for call in calls))
        script = next(call[2] for call in calls if "Submit IHSS timesheet" in " ".join(call))
        self.assertIn('keystroke "continue"', next(call[2] for call in calls if "ChatGPT" in " ".join(call)))
        self.assertNotIn("os.system", script)
        for call in calls:
            self.assertIsInstance(call, list)
            self.assertNotEqual(call[0], "defaults")
            self.assertFalse(str(call[0]).endswith("brightness"))
        self.assertNotIn("brightness", which_names)
        self.assertTrue(joined)


class TestWorkSchoolMoney(unittest.TestCase):
    def test_shift_titles(self):
        self.assertTrue(commands.is_shift_title("R345 - Promenade Temecula"))
        self.assertTrue(commands.is_shift_title("Closing shift"))
        self.assertFalse(commands.is_shift_title("Lunch with Zoe"))
        self.assertFalse(commands.is_shift_title("R3 too short"))

    def test_weekend_and_shift_length(self):
        now = _at(2026, 9, 29, 8, 0)
        saturday = _at(2026, 10, 3, 9, 0)
        events = [
            {"title": "R345 - Promenade Temecula", "start": saturday,
             "end": saturday + timedelta(hours=8), "all_day": False},
            {"title": "Zoe school play", "start": saturday + timedelta(hours=1),
             "end": saturday + timedelta(hours=2), "all_day": False},
        ]
        spoken = commands.describe_work_weekend(events, now)
        self.assertIn("working this weekend", spoken)
        self.assertIn("Saturday", spoken)
        self.assertIn("R345", spoken)
        self.assertNotIn("school play", spoken)
        length = commands.describe_shift_length(events, now)
        self.assertIn("8 hours", length)
        self.assertIn("R345", length)
        clear = commands.describe_work_weekend([events[1]], now)
        self.assertIn("not working", clear)
        during = commands.describe_shift_length(events, saturday + timedelta(hours=2))
        self.assertIn("left", during)

    def test_school_rent_bills_and_brea_read_due_md(self):
        today = datetime(2026, 9, 29).date()
        body = "\n".join([
            "- 2026-09-28 Yesterday's rent",
            "- 2026-10-01 Pay rent",
            "- 2026-10-03 Start at Brea",
            "- 2026-10-05 UMGC discussion post #umgc",
            "- 2026-10-06 classic car show",
            "- 2026-10-08 Buy milk",
            "- 2026-12-01 UMGC final",
            "- no date here",
        ])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "due.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(body)
            school = commands.speak_school_due(today=today, path=path)
            rent = commands.speak_rent(today=today, path=path)
            bills = commands.speak_bills(today=today, path=path)
            brea = commands.brea_from_due(path=path, today=today)
        self.assertIn("UMGC discussion", school)
        self.assertNotIn("classic", school)
        self.assertNotIn("final", school)
        self.assertNotIn("milk", school)
        self.assertIn("rent", rent.lower())
        self.assertIn("October", rent)
        self.assertNotIn("Yesterday", rent)
        self.assertIn("rent", bills.lower())
        self.assertNotIn("milk", bills.lower())
        self.assertIn("Brea", brea)
        self.assertIn("October", brea)
        self.assertIn("in 4 days", brea)

    def test_due_horizon_stays_seven_days(self):
        today = datetime.now().astimezone().date()
        soon = today + timedelta(days=2)
        later = today + timedelta(days=8)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "due.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(f"- {soon.isoformat()} Soon item\n- {later.isoformat()} Later item\n")
            with mock.patch.object(commands, "DUE_PATH", path):
                spoken = commands.speak_due()
        self.assertIn("Soon item", spoken)
        self.assertNotIn("Later item", spoken)

    def test_payday_schedule_is_local(self):
        today = datetime(2026, 9, 29).date()
        self.assertEqual(commands.next_biweekly(datetime(2026, 9, 25).date(), today), datetime(2026, 10, 9).date())
        self.assertEqual(commands.next_semi_payday(today), datetime(2026, 9, 30).date())
        self.assertEqual(commands.next_semi_payday(datetime(2026, 10, 16).date()), datetime(2026, 10, 31).date())
        self.assertEqual(commands._semi_period(datetime(2026, 9, 15).date())[1].day, 15)
        self.assertEqual(commands._semi_period(datetime(2026, 9, 16).date())[0].day, 16)

        def boom(*_args, **_kwargs):
            raise AssertionError("payday tried to run a process")

        with mock.patch.object(commands.subprocess, "run", boom):
            spoken = commands.speak_payday(today=today, path=os.path.join(tempfile.gettempdir(), "missing-money.md"))
        self.assertIn("October", spoken)
        self.assertIn("IHSS", spoken)
        self.assertIn("money.md", spoken)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "money.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("# local only\napple: 2026-10-09\nihss: semi-monthly\n")
            anchored = commands.speak_payday(today=today, path=path)
        self.assertIn("October 9th", anchored)
        self.assertNotIn("default schedule", anchored)

    def test_info_payday_uses_the_real_money_path(self):
        """The live route reads ~/Documents/Jev/money.md. Do not patch that constant."""
        self.assertEqual(commands.route_before_api("how long until payday"), "info_payday")
        self.assertEqual(commands.MONEY_PATH, os.path.expanduser("~/Documents/Jev/money.md"))
        self.assertFalse(hasattr(commands, "MONEY_PATH") and commands.MONEY_PATH is None)
        spoken = commands.speak_payday(today=datetime(2026, 9, 29).date())
        self.assertIn("Apple payday", spoken)
        self.assertIn("IHSS payday", spoken)
        if not os.path.isfile(commands.MONEY_PATH):
            self.assertIn("September 30th", spoken)
            self.assertIn("October 9th", spoken)
            self.assertIn("default schedule", spoken)
            self.assertIn("money.md", spoken)

    def test_grandma_hours_append_and_period_total(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ihss_hours.csv")
            with mock.patch.object(commands, "IHSS_PATH", path):
                logged = commands.log_ihss("log 2.5 hours for grandma")
                logged_old = commands.log_ihss("log IHSS hours: 1 hour today")
                total = commands.speak_ihss_period()
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        self.assertIn("2.5", text)
        self.assertIn("Logged", logged)
        self.assertIn("Logged", logged_old)
        self.assertIn("3.5", total.replace("3.50", "3.5"))


class TestShortcutSafety(unittest.TestCase):
    def setUp(self):
        commands.clear_shortcut_cache()
        commands.clear_confirmation()

    def test_missing_folder_ignores_the_unfiltered_list(self):
        catalog = commands.catalog_from_listings(FOLDERS_NO_JEV, ALL_SHORTCUTS, ALL_SHORTCUTS, ALL_SHORTCUTS)
        self.assertIsNone(catalog)

    def test_name_filter_that_returns_everything_is_replaced_by_the_identifier_filter(self):
        catalog = commands.catalog_from_listings(FOLDERS, ALL_SHORTCUTS, JEV_SHORTCUTS, ALL_SHORTCUTS)
        self.assertEqual(set(catalog), {FOCUS, ZOE, LEAVE})
        self.assertNotIn(SEND, catalog)

    def test_identifier_list_failure_refuses_an_unfiltered_name_list(self):
        self.assertIsNone(commands.catalog_from_listings(FOLDERS, ALL_SHORTCUTS, None, ALL_SHORTCUTS))
        subset = commands.catalog_from_listings(FOLDERS, JEV_SHORTCUTS, None, ALL_SHORTCUTS)
        self.assertEqual(set(subset), {FOCUS, ZOE, LEAVE})

    def test_empty_folder_is_empty(self):
        catalog = commands.catalog_from_listings(FOLDERS, "", "", ALL_SHORTCUTS)
        self.assertEqual(catalog, {})

    def test_loader_does_not_ask_for_folder_names_when_jev_is_missing(self):
        calls = []

        def fake_run(args, **kwargs):
            calls.append(list(args))
            if "--folders" in args:
                return _cp(args, FOLDERS_NO_JEV)
            if "--folder-name" in args:
                return _cp(args, ALL_SHORTCUTS)
            return _cp(args, ALL_SHORTCUTS)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            self.assertIsNone(commands.jev_shortcut_catalog(force=True))
            refused = commands.run_named_shortcut("run shortcut Send Money")
        self.assertIn("didn't run", refused)
        self.assertFalse(any("--folder-name" in call for call in calls))
        self.assertFalse(any(call[:2] == ["shortcuts", "run"] for call in calls))

    def test_run_uses_the_folder_identifier_only(self):
        calls = []

        def fake_run(args, **kwargs):
            args = list(args)
            calls.append(args)
            if "--folders" in args:
                return _cp(args, FOLDERS)
            if "--folder-name" in args:
                which = args[args.index("--folder-name") + 1]
                if which in (FOLDER, "Jev"):
                    stdout = ALL_SHORTCUTS if which == "Jev" else JEV_SHORTCUTS
                    return _cp(args, stdout)
            if args[:3] == ["shortcuts", "list", "--show-identifiers"]:
                return _cp(args, ALL_SHORTCUTS)
            if args[:2] == ["shortcuts", "run"]:
                return _cp(args)
            return _cp(args, code=1)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            commands.clear_shortcut_cache()
            ran = commands.run_named_shortcut("run shortcut Leaving for work")
            missing = commands.run_named_shortcut("run shortcut Send Money")
            fuzzy = commands.run_named_shortcut("run leaving")
            outside = commands.run_named_shortcut("run send money")
        runs = [call for call in calls if call[:2] == ["shortcuts", "run"]]
        self.assertEqual(runs, [["shortcuts", "run", LEAVE], ["shortcuts", "run", LEAVE]])
        self.assertEqual(ran, "Ran Leaving for work.")
        self.assertIn("couldn't find", missing)
        self.assertIn("Ran Leaving", fuzzy)
        self.assertIn("couldn't find", outside)
        for call in calls:
            self.assertIsInstance(call, list)

    def test_princess_academy_does_not_run_an_outside_shortcut(self):
        calls = []

        def fake_run(args, **kwargs):
            args = list(args)
            calls.append(args)
            if "--folders" in args:
                return _cp(args, FOLDERS)
            if "--folder-name" in args:
                return _cp(args, _line("Jev Focus On", FOCUS) + "\n")
            if args[:3] == ["shortcuts", "list", "--show-identifiers"]:
                return _cp(args, ALL_SHORTCUTS)
            return _cp(args)

        with mock.patch.object(commands.subprocess, "run", fake_run):
            commands.clear_shortcut_cache()
            with mock.patch.object(commands, "PRINCESS_ACADEMY_URL", ""):
                spoken = commands.open_princess_academy()
        self.assertIn("isn't in the Jev folder", spoken)
        self.assertFalse(any(call[:2] == ["shortcuts", "run"] for call in calls))


if __name__ == "__main__":
    unittest.main()
