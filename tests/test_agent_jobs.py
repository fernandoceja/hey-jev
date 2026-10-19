"""Agent job queue and status check: local JSON files in a temp folder. No network."""
import json
import os
import socket
import stat
import tempfile
import unittest
from unittest import mock

import commands
from commands import agent_jobs as aj
from commands.bridge import bridge_allowed
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api
from commands.zoe_mode import zoe_allows


class AgentJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.jobs_dir = os.path.join(self.tmp.name, "agent-jobs")

    def tearDown(self):
        self.tmp.cleanup()

    def test_routing_and_off_the_bridge(self):
        job_phrases = (
            "have an agent build a habit tracker",
            "ask an agent to research solar panels",
            "Hey Jev, have an agent build a landing page and add dark mode",
            "please ask an agent to research macOS menu bar apps",
            "have my agent summarize the release notes",
            "tell an agent to draft a changelog",
            "have an agent buy headphones",
        )
        for phrase in job_phrases:
            self.assertEqual(route_before_api(phrase), "agent_job", phrase)
            self.assertIsNone(bridge_allowed(phrase), phrase)

        status_phrases = (
            "what's my agent doing",
            "what is my agent doing",
            "agent status",
            "what's the agent status",
            "check my agent status",
            "how's my agent doing",
            "what's my agent working on",
        )
        for phrase in status_phrases:
            self.assertEqual(route_before_api(phrase), "agent_status", phrase)
            self.assertIsNone(bridge_allowed(phrase), phrase)

        for key in ("agent_job", "agent_status"):
            self.assertNotIn(key, BRIDGE_ALLOW)
            self.assertFalse(zoe_allows(key))

    def test_default_dir_is_in_application_support(self):
        self.assertTrue(
            aj.DEFAULT_AGENT_JOBS_DIR.endswith(
                os.path.join("Library", "Application Support", "Hey Jev", "agent-jobs")
            )
        )
        self.assertEqual(
            aj.agent_jobs_dir(env={"JEV_AGENT_JOBS_DIR": self.jobs_dir}),
            self.jobs_dir,
        )

    def test_queue_writes_job_file_and_speaks_confirmation(self):
        reply = aj.queue_agent_job(
            "have an agent build a habit tracker",
            jobs_dir=self.jobs_dir,
            now="2026-10-18T08:42:27-07:00",
            job_id="job001",
            platform="darwin",
        )
        self.assertEqual(reply, "Got it, I queued that for your agent.")
        path = os.path.join(self.jobs_dir, "job001.json")
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(
            [n for n in os.listdir(self.jobs_dir) if n.endswith(".tmp")],
            [],
        )
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertEqual(
            data,
            {
                "id": "job001",
                "text": "build a habit tracker",
                "time": "2026-10-18T08:42:27-07:00",
                "status": "queued",
            },
        )

    def test_parse_ask_an_agent_to_research(self):
        self.assertEqual(
            aj.parse_agent_job("ask an agent to research local TTS models"),
            "research local TTS models",
        )
        self.assertEqual(
            aj.parse_agent_job("have an agent build a budget dashboard"),
            "build a budget dashboard",
        )
        self.assertIsNone(aj.parse_agent_job("have an agent"))
        self.assertEqual(
            aj.queue_agent_job("have an agent", jobs_dir=self.jobs_dir, platform="darwin"),
            aj.AGENT_UNCLEAR,
        )

    def test_rejects_money_purchase_and_transfer_jobs(self):
        refused = (
            "have an agent buy AirPods on Amazon",
            "ask an agent to pay my electric bill",
            "have an agent transfer money to savings",
            "ask an agent to purchase a domain name",
            "have an agent send $50 to Sam",
            "ask an agent to wire funds to the vendor",
            "have an agent spend 20 dollars on credits",
            "ask an agent to checkout my cart",
            "have an agent venmo Alex",
            "have an agent order AirPods on Amazon",
            "have an agent place an order for a laptop",
            "ask an agent to reorder my vitamins",
            "have an agent pre-order the new iPhone",
            "ask an agent to go online and order me a pizza",
            "have an agent donate to the Red Cross",
            "ask an agent to research options and order AirPods",
            "have an agent compare laptops, then order the cheapest one",
            "ask an agent to find a good charger and reorder batteries",
        )
        for phrase in refused:
            reply = aj.queue_agent_job(
                phrase,
                jobs_dir=self.jobs_dir,
                platform="darwin",
            )
            self.assertEqual(reply, aj.AGENT_MONEY_REFUSED, phrase)
        self.assertFalse(os.path.exists(self.jobs_dir))

    def test_order_wording_that_is_not_buying_still_queues(self):
        allowed = (
            "have an agent research cars in order to compare prices",
            "ask an agent to sort my notes in date order",
            "have an agent build an order of operations quiz",
            "ask an agent to research tools and order of operations",
            "have an agent list my files and order by date",
            "ask an agent to research cars and sort them in price order",
        )
        for phrase in allowed:
            self.assertFalse(aj.is_money_job(aj.parse_agent_job(phrase)), phrase)
            self.assertEqual(
                aj.queue_agent_job(phrase, jobs_dir=self.jobs_dir, platform="darwin"),
                aj.AGENT_QUEUED,
                phrase,
            )

    def test_status_reads_latest_jobs_and_external_updates(self):
        self.assertEqual(
            aj.speak_agent_status(jobs_dir=self.jobs_dir, platform="darwin"),
            aj.AGENT_EMPTY,
        )
        aj.queue_agent_job(
            "have an agent build a habit tracker",
            jobs_dir=self.jobs_dir,
            now="2026-10-18T08:00:00-07:00",
            job_id="job1",
            platform="darwin",
        )
        aj.queue_agent_job(
            "ask an agent to research solar panels",
            jobs_dir=self.jobs_dir,
            now="2026-10-18T08:30:00-07:00",
            job_id="job2",
            platform="darwin",
        )
        # Simulate Grok Bot Chief of Staff updating job1 and job2 statuses.
        with open(os.path.join(self.jobs_dir, "job1.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "job1",
                    "text": "build a habit tracker",
                    "time": "2026-10-18T08:00:00-07:00",
                    "status": "done",
                    "summary": "Prototype saved in scratch",
                },
                f,
            )
        with open(os.path.join(self.jobs_dir, "job2.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "id": "job2",
                    "text": "research solar panels",
                    "time": "2026-10-18T08:30:00-07:00",
                    "status": "in_progress",
                },
                f,
            )
        line = aj.speak_agent_status(jobs_dir=self.jobs_dir, platform="darwin")
        self.assertEqual(
            line,
            "research solar panels is in progress. build a habit tracker is done: Prototype saved in scratch.",
        )

    def test_status_ignores_symlinks_and_corrupt_files(self):
        os.makedirs(self.jobs_dir, exist_ok=True)
        with open(os.path.join(self.jobs_dir, "bad.json"), "w", encoding="utf-8") as f:
            f.write("not valid json")
        secret = os.path.join(self.tmp.name, "secret.json")
        with open(secret, "w", encoding="utf-8") as f:
            json.dump({"id": "sec", "text": "secret task", "time": 999, "status": "queued"}, f)
        os.symlink(secret, os.path.join(self.jobs_dir, "link.json"))
        self.assertEqual(
            aj.speak_agent_status(jobs_dir=self.jobs_dir, platform="darwin"),
            aj.AGENT_EMPTY,
        )

    def test_mac_only(self):
        self.assertEqual(
            aj.queue_agent_job(
                "have an agent build X",
                jobs_dir=self.jobs_dir,
                platform="linux",
            ),
            aj.AGENT_NOT_MAC,
        )
        self.assertFalse(os.path.exists(self.jobs_dir))
        self.assertEqual(
            aj.speak_agent_status(jobs_dir=self.jobs_dir, platform="linux"),
            aj.AGENT_NOT_MAC,
        )

    def test_no_sockets_opened(self):
        def boom(*_a, **_k):
            raise AssertionError("socket opened")

        with mock.patch.object(socket, "socket", boom):
            aj.queue_agent_job(
                "ask an agent to research X",
                jobs_dir=self.jobs_dir,
                platform="darwin",
            )
            aj.speak_agent_status(jobs_dir=self.jobs_dir, platform="darwin")

    def test_exports(self):
        self.assertIs(commands.queue_agent_job, aj.queue_agent_job)
        self.assertIs(commands.speak_agent_status, aj.speak_agent_status)


if __name__ == "__main__":
    unittest.main()
