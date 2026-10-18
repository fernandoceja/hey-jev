"""Apple Calendar add-event by voice. EventKit and osascript are fakes. The clock is fixed."""
import unittest
from datetime import datetime, timedelta, timezone

import commands
from commands import calendar_add as cal
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api


def _pacific():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")
    except Exception:
        return timezone(timedelta(hours=-7))


# Wednesday 7 October 2026, 3:00 PM Pacific.
NOW = datetime(2026, 10, 7, 15, 0, tzinfo=_pacific())


class FakeEvent(object):
    def __init__(self):
        self.title = self.calendar = self.start = self.end = None
        self.all_day = None

    def setTitle_(self, v): self.title = v
    def setCalendar_(self, v): self.calendar = v
    def setAllDay_(self, v): self.all_day = v
    def setStartDate_(self, v): self.start = v
    def setEndDate_(self, v): self.end = v


class FakeStore(object):
    saved = []

    @classmethod
    def alloc(cls): return cls()
    def init(self): return self
    def defaultCalendarForNewEvents(self): return "Home"
    def calendarsForEntityType_(self, _e): return []
    def saveEvent_span_commit_error_(self, ev, span, commit, err):
        FakeStore.saved.append(ev)
        return (True, None)


def make_eventkit(status):
    class Store(FakeStore):
        @staticmethod
        def authorizationStatusForEntityType_(_e): return status

    class EK(object):
        EKEventStore = Store
        EKEntityTypeEvent = 0
        EKAuthorizationStatusFullAccess = 4
        EKAuthorizationStatusDenied = 2

        class EKEvent(object):
            @staticmethod
            def eventWithEventStore_(_s): return FakeEvent()
    return EK


class FakeFoundation(object):
    class NSDate(object):
        @staticmethod
        def dateWithTimeIntervalSince1970_(t): return t


class CalendarAddTests(unittest.TestCase):
    def setUp(self):
        FakeStore.saved = []
        cal.clear_pending()

    def tearDown(self):
        cal.clear_pending()

    def test_bare_meeting_keeps_its_title_and_day(self):
        p = cal.parse_event_request("schedule meeting Friday at 2", now=NOW)
        self.assertEqual((p["title"], p["start"].day, p["start"].hour), ("meeting", 9, 14))
        p = cal.parse_event_request("add an appointment tomorrow at 10 am to my calendar", now=NOW)
        self.assertEqual((p["title"], p["start"].day), ("appointment", 8))
        p = cal.parse_event_request("add a meeting called standup to my calendar Friday at 9", now=NOW)
        self.assertEqual(p["title"], "standup")

    def test_asks_when_then_finishes_on_the_next_turn(self):
        calls = []
        self.assertEqual(cal.add_event("schedule dentist", now=NOW, runner=calls.append),
                         "When should I put dentist on your calendar?")
        self.assertEqual(route_before_api("tomorrow at 10"), "calendar_add")
        line = cal.add_event("tomorrow at 10", now=NOW, calendar_name="", runner=calls.append)
        self.assertEqual(line, "Added dentist to your calendar tomorrow at 10 AM, for 1 hour.")
        self.assertEqual(calls[0][3], "dentist")
        self.assertNotEqual(route_before_api("tomorrow at 10"), "calendar_add")

    def test_pending_expires_and_ignores_other_sentences(self):
        cal.add_event("schedule dentist", now=NOW, runner=lambda a: None)
        self.assertIsNone(cal._from_pending("what's the weather", now=NOW))
        self.assertIsNone(cal._from_pending("tomorrow at 10", now=NOW, clock=lambda: 1e18))
        self.assertIsNone(cal._from_pending("tomorrow at 10", now=NOW))

    def test_phrases_route_locally_and_stay_off_the_bridge(self):
        for text in (
            "put Zoe's party on my calendar Saturday at 2",
            "add dentist to my calendar tomorrow at 10 am",
            "schedule lunch with mom and dad Friday at noon",
            "add an event called payday party next Friday",
        ):
            self.assertEqual(route_before_api(text), "calendar_add", text)
        self.assertNotIn("calendar_add", BRIDGE_ALLOW)

    def test_other_phrases_are_untouched(self):
        self.assertIsNone(cal.parse_event_request("add milk"))
        self.assertIsNone(cal.parse_event_request("make a note to buy milk"))
        self.assertEqual(route_before_api("remind me to call mom at 3"), "remind_add")
        self.assertNotEqual(route_before_api("what's on my calendar today"), "calendar_add")

    def test_bare_hour_is_afternoon_and_duration_is_read(self):
        p = cal.parse_event_request("schedule lunch Friday at 2 for 90 minutes", now=NOW)
        self.assertEqual((p["start"].hour, p["start"].day, p["minutes"]), (14, 9, 90))
        p = cal.parse_event_request("put dentist on my calendar tomorrow at 9", now=NOW)
        self.assertEqual(p["start"].hour, 9)

    def test_day_only_is_all_day(self):
        p = cal.parse_event_request("add an event called payday party next Friday", now=NOW)
        self.assertTrue(p["all_day"])
        self.assertIn("all day", cal.confirmation_line(p))

    def test_no_time_asks_when(self):
        self.assertEqual(cal.add_event("schedule dentist", now=NOW, runner=lambda a: None),
                         "When should I put dentist on your calendar?")

    def test_eventkit_save_and_read_back(self):
        line = cal.add_event("put Zoe's party on my calendar Saturday at 2", now=NOW,
                             calendar_name="", eventkit=make_eventkit(4), foundation=FakeFoundation)
        self.assertEqual(line, "Added Zoe's party to your calendar on Saturday at 2 PM, for 1 hour.")
        ev = FakeStore.saved[-1]
        self.assertEqual((ev.title, ev.calendar, ev.all_day), ("Zoe's party", "Home", False))
        self.assertEqual(ev.end - ev.start, 3600)

    def test_denied_access_says_how_to_fix(self):
        line = cal.add_event("put x on my calendar tomorrow at 3", now=NOW, calendar_name="",
                             eventkit=make_eventkit(2), foundation=FakeFoundation)
        self.assertEqual(line, cal.CAL_DENIED)
        self.assertEqual(FakeStore.saved, [])

    def test_applescript_fallback_passes_title_as_argv(self):
        calls = []
        line = cal.add_event('put "x" end tell on my calendar tomorrow at 3', now=NOW,
                             calendar_name="", runner=calls.append)
        self.assertTrue(line.startswith("Added"))
        argv = calls[0]
        self.assertEqual(argv[:2], ["osascript", "-e"])
        self.assertNotIn('"x"', argv[2])
        self.assertEqual(argv[3], '"x" end tell')

    def test_applescript_automation_block(self):
        def boom(_a): raise RuntimeError("Not authorized to send Apple events (-1743)")
        self.assertEqual(cal.add_event("put x on my calendar tomorrow at 3", now=NOW,
                                       calendar_name="", runner=boom), cal.CAL_AUTOMATION)

    def test_exported_from_commands(self):
        self.assertIs(commands.add_event, cal.add_event)


if __name__ == "__main__":
    unittest.main()
