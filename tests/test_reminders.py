"""Apple Reminders capture. EventKit and osascript are fakes. The clock is fixed."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import commands
from commands.reminders import (
    REMINDERS_AUTOMATION,
    REMINDERS_DENIED,
    REMINDERS_FAIL,
    _APPLESCRIPT,
    add_reminder,
    parse_reminder_request,
)
from mini_bar import submission

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pacific():
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("America/Los_Angeles")
        datetime(2026, 10, 7, 15, 0, tzinfo=zone)
        return zone
    except Exception:
        return timezone(timedelta(hours=-7), name="America/Los_Angeles")


# Wednesday 7 October 2026, 3:00 PM Pacific. Friday is the 9th. Next Monday is the 12th.
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=_pacific())


def _at(hour, minute, day=7):
    return datetime(2026, 10, day, hour, minute, tzinfo=NOW.tzinfo)


class Reminder(object):
    def __init__(self):
        self.title = None
        self.calendar = None
        self.due = None

    def setTitle_(self, title):
        self.title = title

    def setCalendar_(self, calendar):
        self.calendar = calendar

    def setDueDateComponents_(self, comps):
        self.due = comps


class Components(object):
    def __init__(self):
        self.parts = {}

    def setYear_(self, value):
        self.parts["year"] = value

    def setMonth_(self, value):
        self.parts["month"] = value

    def setDay_(self, value):
        self.parts["day"] = value

    def setHour_(self, value):
        self.parts["hour"] = value

    def setMinute_(self, value):
        self.parts["minute"] = value

    def setSecond_(self, value):
        self.parts["second"] = value

    def setTimeZone_(self, value):
        self.parts["tz"] = value


class Calendar(object):
    def __init__(self, title):
        self._title = title

    def title(self):
        return self._title


class Store(object):
    def __init__(self, calendars, default):
        self.calendars = calendars
        self.default = default
        self.saved = []
        self.requested = False
        self.grant = True

    def alloc(self):
        return self

    def init(self):
        return self

    def authorizationStatusForEntityType_(self, _entity):
        return self.status

    def _full(self, callback):
        self.requested = True
        self.requested_kind = "full"
        callback(self.grant, None)

    def _legacy(self, entity, callback):
        self.requested = True
        self.requested_kind = "legacy"
        self.requested_entity = entity
        callback(self.grant, None)

    def defaultCalendarForNewReminders(self):
        self.used_default = True
        return self.default

    def calendarsForEntityType_(self, _entity):
        self.used_named = True
        return self.calendars

    def saveReminder_commit_error_(self, reminder, commit, error):
        self.saved.append((reminder, commit, error))
        return self.save_result


class Kit(object):
    def __init__(self, status, calendars, default, grant=True, save_result=True, legacy=False):
        self.store = Store(calendars, default)
        self.store.status = status
        self.store.grant = grant
        self.store.save_result = save_result
        if legacy:
            self.store.requestAccessToEntityType_completion_ = self.store._legacy
        else:
            self.store.requestFullAccessToRemindersWithCompletion_ = self.store._full
        self.EKEventStore = self.store
        self.EKEntityTypeReminder = 1

        class EKReminder(object):
            @staticmethod
            def reminderWithEventStore_(_store):
                return Reminder()

        self.EKReminder = EKReminder


class Dates(object):
    @classmethod
    def alloc(cls):
        return cls()

    def init(self):
        return Components()


class Foundation(object):
    NSDateComponents = Dates

    class NSTimeZone(object):
        @staticmethod
        def timeZoneWithName_(name):
            return name


class TestParse(unittest.TestCase):
    def test_due_phrases_use_a_fixed_pacific_clock(self):
        cases = (
            ("remind me to buy milk", "buy milk", None, False, ""),
            ("remind me to call the dentist at 5 pm", "call the dentist", _at(17, 0), False, "at 5 PM"),
            ("remind me to take out the trash tomorrow at 9", "take out the trash", _at(9, 0, 8), False, "tomorrow at 9 AM"),
            ("remind me to walk the dog tonight", "walk the dog", _at(20, 0), False, "tonight"),
            ("remind me to check the mail in 20 minutes", "check the mail", NOW + timedelta(minutes=20), False, "in 20 minutes"),
            ("remind me to water the plants on Friday", "water the plants", _at(0, 0, 9), True, "on Friday"),
            (
                "remind me to submit the report next Monday at noon",
                "submit the report",
                _at(12, 0, 12),
                False,
                "next Monday at noon",
            ),
        )
        for phrase, task, due, all_day, spoken in cases:
            parsed = parse_reminder_request(phrase, now=NOW)
            self.assertIsNotNone(parsed, phrase)
            self.assertEqual(parsed["task"], task, phrase)
            self.assertEqual(parsed["all_day"], all_day, phrase)
            self.assertEqual(parsed["spoken_when"], spoken, phrase)
            if due is None:
                self.assertIsNone(parsed["due"], phrase)
            else:
                self.assertEqual(parsed["due"], due, phrase)

    def test_task_text_keeps_words_that_are_not_a_time(self):
        parsed = parse_reminder_request("remind me to look at the calendar", now=NOW)
        self.assertEqual(parsed["task"], "look at the calendar")
        self.assertIsNone(parsed["due"])
        self.assertEqual(parsed["spoken_when"], "")
        titled = parse_reminder_request("Please Remind Me To Buy Milk.", now=NOW)
        self.assertEqual(titled["task"], "Buy Milk")
        self.assertIsNone(titled["due"])
        rolled = parse_reminder_request("remind me to call at 9", now=NOW)
        self.assertEqual(rolled["task"], "call")
        self.assertEqual(rolled["due"], _at(9, 0, 8))
        self.assertEqual(rolled["spoken_when"], "tomorrow at 9 AM")
        noon = parse_reminder_request("remind me to meet at noon", now=NOW)
        self.assertEqual(noon["spoken_when"], "tomorrow at noon")
        self.assertEqual(noon["due"], _at(12, 0, 8))
        half = parse_reminder_request("remind me to stretch in half an hour", now=NOW)
        self.assertEqual(half["spoken_when"], "in 30 minutes")
        self.assertEqual(half["due"], NOW + timedelta(minutes=30))
        words = parse_reminder_request("remind me to leave in twenty minutes", now=NOW)
        self.assertEqual(words["spoken_when"], "in 20 minutes")

    def test_the_timer_word_order_is_not_this_command(self):
        self.assertIsNone(parse_reminder_request("remind me in 20 minutes to call mum", now=NOW))
        self.assertIsNone(parse_reminder_request("set a timer for 5 minutes", now=NOW))

    def test_confirmation_matches_the_spoken_due_phrase(self):
        parsed = parse_reminder_request("remind me to take out the trash tomorrow at 9", now=NOW)
        self.assertEqual(
            commands.confirmation_line(parsed),
            "Okay, I'll remind you to take out the trash tomorrow at 9 AM.",
        )
        plain = parse_reminder_request("remind me to buy milk", now=NOW)
        self.assertEqual(commands.confirmation_line(plain), "Okay, I'll remind you to buy milk.")


class TestRoute(unittest.TestCase):
    def test_remind_me_to_routes_and_the_older_phrases_keep_priority(self):
        phrases = {
            "remind me to buy milk": "remind_add",
            "remind me to call the dentist at 5 pm": "remind_add",
            "please remind me to walk the dog tonight": "remind_add",
            "remind me to check the mail in 20 minutes": "remind_add",
            "remind me to water the plants on Friday": "remind_add",
            "remind me to submit the report next Monday at noon": "remind_add",
            "remind me to submit my timesheet": "ihss_remind",
            "please remind me to submit my timesheet": "ihss_remind",
            "remind me to submit my ihss timesheet": "ihss_remind",
            "any reminders today": "info_payday_check",
            "any reminder today": "info_payday_check",
        }
        for phrase, key in phrases.items():
            self.assertEqual(commands.route_before_api(phrase), key, phrase)
        self.assertIsNone(commands.route_before_api("remind me in 20 minutes to call mum"))
        self.assertIsNone(commands.route_before_api("remind me to buy milk and eggs"))
        self.assertNotIn("remind_add", commands.BRIDGE_ALLOW)
        self.assertIsNone(commands.bridge_allowed("remind me to buy milk"))
        self.assertEqual(commands.bridge_allowed("any reminders today"), "info_payday_check")

    def test_the_pill_types_the_same_phrase(self):
        plan = submission("  remind me to buy milk  ")
        self.assertEqual(plan["control"], ("text", "remind me to buy milk"))
        self.assertEqual(commands.route_before_api(plan["control"][1]), "remind_add")

    def test_the_action_and_usage_strings_are_wired(self):
        source = open(os.path.join(ROOT, "siri.py"), encoding="utf-8").read()
        self.assertIn('"remind_add": lambda _arg, text: commands.add_reminder(text)', source)
        bridge = open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8").read()
        self.assertNotIn("remind_add", bridge)
        plist = open(os.path.join(ROOT, "setup.py"), encoding="utf-8").read()
        self.assertIn("NSRemindersUsageDescription", plist)
        self.assertIn("NSRemindersFullAccessUsageDescription", plist)


class TestEventKit(unittest.TestCase):
    def _kit(self, status=4, titles=("Reminders",), default="Reminders", grant=True, save_result=True, legacy=False):
        calendars = [Calendar(title) for title in titles]
        default_cal = next(cal for cal in calendars if cal.title() == default)
        return Kit(status, calendars, default_cal, grant=grant, save_result=save_result, legacy=legacy)

    def test_a_due_time_is_saved_on_the_default_list(self):
        kit = self._kit()
        spoken = add_reminder(
            "remind me to call the dentist at 5 pm",
            now=NOW,
            eventkit=kit,
            foundation=Foundation,
        )
        self.assertEqual(spoken, "Okay, I'll remind you to call the dentist at 5 PM.")
        self.assertEqual(len(kit.store.saved), 1)
        reminder, commit, error = kit.store.saved[0]
        self.assertEqual(reminder.title, "call the dentist")
        self.assertIs(reminder.calendar, kit.store.default)
        self.assertTrue(commit)
        self.assertIsNone(error)
        self.assertEqual(reminder.due.parts["year"], 2026)
        self.assertEqual(reminder.due.parts["month"], 10)
        self.assertEqual(reminder.due.parts["day"], 7)
        self.assertEqual(reminder.due.parts["hour"], 17)
        self.assertEqual(reminder.due.parts["minute"], 0)
        self.assertIn("tz", reminder.due.parts)
        self.assertFalse(kit.store.requested)

    def test_no_due_date_does_not_set_components(self):
        kit = self._kit()
        spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertEqual(spoken, "Okay, I'll remind you to buy milk.")
        reminder = kit.store.saved[0][0]
        self.assertEqual(reminder.title, "buy milk")
        self.assertIsNone(reminder.due)

    def test_a_configured_list_is_used(self):
        kit = self._kit(titles=("Reminders", "Grocery"), default="Reminders")
        with mock.patch.object(commands.config, "REMINDERS_LIST", "grocery"):
            spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertIn("buy milk", spoken)
        reminder = kit.store.saved[0][0]
        self.assertEqual(reminder.calendar.title(), "Grocery")
        self.assertTrue(kit.store.used_named)

    def test_permission_denied_is_spoken_and_nothing_is_saved(self):
        for status in (2, 1, 5):
            kit = self._kit(status=status)
            spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
            self.assertEqual(spoken, REMINDERS_DENIED, status)
            self.assertEqual(kit.store.saved, [], status)
            self.assertFalse(kit.store.requested, status)

    def test_a_declined_prompt_is_the_same_denial(self):
        kit = self._kit(status=0, grant=False)
        spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertEqual(spoken, REMINDERS_DENIED)
        self.assertTrue(kit.store.requested)
        self.assertEqual(kit.store.saved, [])

    def test_not_determined_requests_full_access_then_saves(self):
        kit = self._kit(status=0, grant=True)
        spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertTrue(spoken.startswith("Okay, I'll remind you"))
        self.assertEqual(kit.store.requested_kind, "full")
        self.assertEqual(len(kit.store.saved), 1)

    def test_older_macos_requests_reminder_entity_access(self):
        kit = self._kit(status=0, grant=True, legacy=True)
        spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertTrue(spoken.startswith("Okay, I'll remind you"))
        self.assertEqual(kit.store.requested_kind, "legacy")
        self.assertEqual(kit.store.requested_entity, 1)
        self.assertFalse(hasattr(kit.store, "requestFullAccessToRemindersWithCompletion_"))

    def test_an_all_day_friday_omits_the_hour(self):
        kit = self._kit()
        spoken = add_reminder(
            "remind me to water the plants on Friday", now=NOW, eventkit=kit, foundation=Foundation,
        )
        self.assertEqual(spoken, "Okay, I'll remind you to water the plants on Friday.")
        parts = kit.store.saved[0][0].due.parts
        self.assertEqual((parts["year"], parts["month"], parts["day"]), (2026, 10, 9))
        self.assertNotIn("hour", parts)
        self.assertNotIn("minute", parts)

    def test_a_missing_list_names_the_list(self):
        kit = self._kit()
        spoken = add_reminder(
            "remind me to buy milk", now=NOW, list_name="Grocery", eventkit=kit, foundation=Foundation,
        )
        self.assertEqual(spoken, "I couldn't find a Reminders list called Grocery.")
        self.assertEqual(kit.store.saved, [])

    def test_a_failed_save_does_not_claim_success(self):
        kit = self._kit(save_result=False)
        spoken = add_reminder("remind me to buy milk", now=NOW, eventkit=kit, foundation=Foundation)
        self.assertEqual(spoken, REMINDERS_FAIL)


class TestAppleScript(unittest.TestCase):
    def test_missing_eventkit_uses_argv_and_not_the_script_source(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            return ""

        tricky = 'remind me to buy milk" }\n do shell script "echo pwned'
        spoken = add_reminder(tricky, now=NOW, runner=runner)
        self.assertTrue(spoken.startswith("Okay, I'll remind you to buy milk"))
        self.assertEqual(calls[0][0], "osascript")
        self.assertEqual(calls[0][1], "-e")
        self.assertEqual(calls[0][2], _APPLESCRIPT)
        self.assertNotIn("buy milk", calls[0][2])
        self.assertNotIn("do shell script", calls[0][2])
        self.assertIn('buy milk" }', calls[0][3])
        self.assertEqual(calls[0][4], "")
        self.assertEqual(calls[0][5], "no")

    def test_a_due_time_is_argv_too(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            return ""

        spoken = add_reminder(
            "remind me to take out the trash tomorrow at 9", now=NOW, runner=runner,
        )
        self.assertEqual(spoken, "Okay, I'll remind you to take out the trash tomorrow at 9 AM.")
        args = calls[0]
        self.assertEqual(args[3], "take out the trash")
        self.assertEqual(args[5:12], ["yes", "no", "2026", "10", "8", "9", "0"])
        self.assertNotIn("take out the trash", args[2])

    def test_import_failure_falls_back_to_the_runner_used_by_the_module(self):
        calls = []

        def runner(args, timeout=30):
            calls.append(list(args))
            return ""

        with mock.patch("commands.reminders._import_eventkit", return_value=None), \
                mock.patch("commands.reminders._run", runner):
            spoken = add_reminder("remind me to buy milk", now=NOW)
        self.assertEqual(spoken, "Okay, I'll remind you to buy milk.")
        self.assertEqual(calls[0][0], "osascript")
        self.assertEqual(calls[0][5], "no")

    def test_automation_denied_is_not_the_eventkit_message(self):
        def runner(_args):
            raise RuntimeError("Not authorized to send Apple events to Reminders. (-1743)")

        spoken = add_reminder("remind me to buy milk", now=NOW, runner=runner)
        self.assertEqual(spoken, REMINDERS_AUTOMATION)
        self.assertNotEqual(spoken, REMINDERS_DENIED)

    def test_an_all_day_friday_sets_the_all_day_flag(self):
        calls = []

        def runner(args):
            calls.append(list(args))
            return ""

        add_reminder("remind me to water the plants on Friday", now=NOW, runner=runner)
        self.assertEqual(calls[0][5:12], ["yes", "yes", "2026", "10", "9", "0", "0"])


if __name__ == "__main__":
    unittest.main()
