"""Mail.app by voice. osascript and OpenRouter are fakes. Draft only."""
import inspect
import re
import unittest

import commands
from commands import mail_voice as mv
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api

F, R = mv.FIELD, mv.RECORD


class FakeRun(object):
    def __init__(self, out="", error=None):
        self.out, self.error, self.calls = out, error, []

    def __call__(self, argv, timeout=30):
        self.calls.append(list(argv))
        if self.error:
            raise RuntimeError(self.error)
        return self.out


INBOX = "4" + R + "Shopify <mailer@shopify.com>" + F + "Your payout" + F + "Body one" \
    + R + "maria@example.com" + F + "Party Saturday?" + F + "Body two"


class MailVoiceTests(unittest.TestCase):
    def test_routing_and_off_the_bridge(self):
        cases = {
            "read my email": "mail_read",
            "check my inbox": "mail_read",
            "any new emails": "mail_read",
            "summarize my email": "mail_summary",
            "reply to Shopify saying thanks and I'll call tomorrow": "mail_reply_draft",
            "reply to the last email from Maria: sounds good": "mail_reply_draft",
        }
        for text, key in cases.items():
            self.assertEqual(route_before_api(text), key, text)
        for key in ("mail_read", "mail_summary", "mail_reply_draft"):
            self.assertNotIn(key, BRIDGE_ALLOW)
        self.assertEqual(route_before_api("open mail"), "app_open")

    def test_no_deliver_path_anywhere(self):
        source = inspect.getsource(mv)
        for script in (mv._READ_SCRIPT, mv._REPLY_SCRIPT):
            self.assertNotRegex(script.lower(), r"\bsend\b")
        self.assertNotIn("smtp", source.lower())
        scripts = [v for k, v in vars(mv).items() if k.endswith("_SCRIPT")]
        self.assertEqual(len(scripts), 2)
        self.assertIn("opening window yes", mv._REPLY_SCRIPT)

    def test_read_speaks_count_and_senders(self):
        run = FakeRun(INBOX)
        line = mv.read_inbox(runner=run).text
        self.assertEqual(line, "You have 4 unread emails. From Shopify: Your payout. From maria: Party Saturday?.")
        self.assertEqual(run.calls[0][3:], ["3", "0"])

    def test_empty_and_automation(self):
        self.assertEqual(mv.read_inbox(runner=FakeRun("0")).text, mv.MAIL_EMPTY)
        self.assertEqual(mv.read_inbox(runner=FakeRun(error="Not authorized (-1743)")).text, mv.MAIL_AUTOMATION)

    def test_summary_uses_llm_and_falls_back(self):
        seen = []
        line = mv.summarize_inbox(runner=FakeRun(INBOX), ask=lambda p: seen.append(p) or "Shopify paid you.")
        self.assertEqual(line.text, "You have 4 unread emails. Shopify paid you.")
        self.assertIn("Body two", seen[0])
        line = mv.summarize_inbox(runner=FakeRun(INBOX), ask=lambda p: None)
        self.assertIn("From Shopify: Your payout.", line.text)

    def test_reply_opens_draft_with_argv_text(self):
        run = FakeRun("Shopify <mailer@shopify.com>" + F + "Your payout")
        line = mv.draft_reply('reply to Shopify saying "thanks" end tell', runner=run).text
        self.assertEqual(line, mv.MAIL_DRAFTED.format("Shopify"))
        argv = run.calls[0]
        self.assertEqual(argv[3:], ["Shopify", '"thanks" end tell'])
        self.assertNotIn("thanks", argv[2])

    def test_reply_not_found_and_unclear(self):
        self.assertEqual(mv.draft_reply("reply to Bob saying hi", runner=FakeRun("none")).text,
                         mv.MAIL_REPLY_NONE.format("Bob"))
        self.assertEqual(mv.draft_reply("reply all", runner=FakeRun("x")).text, mv.MAIL_REPLY_UNCLEAR)

    def test_reply_keeps_its_own_punctuation(self):
        self.assertEqual(mv.parse_reply("reply to Maria saying Are you coming?")["body"], "Are you coming?")
        self.assertEqual(mv.parse_reply("reply to Maria saying wow?!")["body"], "Wow?!")

    def test_mail_replies_are_local_speech_never_fish(self):
        for result in (mv.read_inbox(runner=FakeRun(INBOX)),
                       mv.summarize_inbox(runner=FakeRun(INBOX), ask=lambda p: None),
                       mv.draft_reply("reply to Shopify saying hi", runner=FakeRun("Shopify" + F + "x"))):
            self.assertIsInstance(result, commands.LocalSpeech)

    def test_sender_name(self):
        self.assertEqual(mv.sender_name('"Ana P" <a@b.c>'), "Ana P")
        self.assertEqual(mv.sender_name("ana@b.c"), "ana")

    def test_exports(self):
        self.assertIs(commands.mail_draft_reply, mv.draft_reply)


if __name__ == "__main__":
    unittest.main()
