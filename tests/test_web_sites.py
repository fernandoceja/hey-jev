"""Fernando's web games/sites: phrases, routing, hardcoded https URLs, not bridged."""
import pathlib
import unittest

from commands import web_sites as ws
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api

ROOT = pathlib.Path(__file__).resolve().parent.parent
STAR = "https://fernandoceja.github.io/Zoe-s-Princess-Academy/starlight-quest/"
BARN = "https://barnaby-pip-rainbow-crayon.fernando-ceja.chatgpt.site/"
CALC = "https://fernandoceja.github.io/calculus-3-visualization/"


class FakeRun:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, argv, timeout=30):
        self.calls.append(tuple(argv))
        if self.fail:
            raise RuntimeError("no")
        return ""


class WebSiteTests(unittest.TestCase):
    CASES = {
        STAR: ("open starlight quest", "Hey Jev, play Starlight Quest.", "open zoe's starlight quest",
               "launch star light quest", "open starlite quest", "play the starlight game",
               "open starlight guest"),
        BARN: ("play barnaby", "open barnaby and pip", "open Barnaby & Pip", "play barnabee",
               "open the rainbow crayon", "play the barnaby game", "open barney pip"),
        CALC: ("open calculus", "open the math site", "open calculus 3", "open calc three",
               "open calcforge", "pull up the calculus site", "open calculus 3 visualization please"),
    }

    def test_phrases_match(self):
        for url, phrases in self.CASES.items():
            for p in phrases:
                entry = ws.match_web_site(p)
                self.assertIsNotNone(entry, p)
                self.assertEqual(entry["url"], url, p)

    def test_non_matches(self):
        for p in ("", "open safari", "what is calculus", "starlight quest", "open notes",
                  "tell me about barnaby", "open my calculus homework folder"):
            self.assertIsNone(ws.match_web_site(p), p)

    def test_routing(self):
        for phrases in self.CASES.values():
            for p in phrases:
                self.assertEqual(route_before_api(p), "web_site_open", p)

    def test_opens_only_hardcoded_https_default_browser(self):
        run = FakeRun()
        self.assertEqual(ws.open_web_site_from_text("play barnaby", platform="darwin", run=run),
                         "Opening Barnaby and Pip.")
        self.assertEqual(run.calls, [("open", BARN)])
        self.assertEqual({e["url"] for e in ws.WEB_SITES}, {STAR, BARN, CALC})
        for e in ws.WEB_SITES:
            self.assertTrue(e["url"].startswith("https://"))
            self.assertTrue(ws._safe(e["url"]))

    def test_unsafe_url_refused(self):
        self.assertFalse(ws._safe("http://example.com"))
        self.assertFalse(ws._safe("https://x.com/;rm -rf"))

    def test_failure_and_not_mac(self):
        self.assertEqual(ws.open_web_site_from_text("open calculus", platform="darwin", run=FakeRun(fail=True)),
                         "I couldn't open the Calculus 3 visualization.")
        run = FakeRun()
        self.assertEqual(ws.open_web_site_from_text("open calculus", platform="linux", run=run), ws.WEB_NOT_MAC)
        self.assertEqual(run.calls, [])
        self.assertEqual(ws.open_web_site_from_text("open nothing", platform="darwin", run=run),
                         "Which site should I open?")

    def test_not_bridged_and_wired(self):
        self.assertNotIn("web_site_open", BRIDGE_ALLOW)
        self.assertIn('"web_site_open": lambda', (ROOT / "siri.py").read_text())


if __name__ == "__main__":
    unittest.main()
