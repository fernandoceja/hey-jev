"""Ask your notes: local keyword search in a temp folder. No network."""
import os
import tempfile
import unittest

import commands
from commands import notes_search as ns
from commands.config import BRIDGE_ALLOW
from commands.routing import route_before_api


class NotesSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        with open(os.path.join(d, "notes.md"), "w") as f:
            f.write("# Notes\n\n- Brea interview went well, feedback in about a week\n"
                    "- buy wigs for Big Hair Bash\n- call mom\n- pick up cake\n- gas\n\n"
                    "Rent is due on the 1st.\n")
        os.mkdir(os.path.join(d, "sub"))
        with open(os.path.join(d, "sub", "zoe.txt"), "w") as f:
            f.write("Zoe's recital is Friday at 6 pm at school.\n")
        with open(os.path.join(d, "skip.pdf"), "w") as f:
            f.write("Brea interview secret")
        os.mkdir(os.path.join(d, ".hidden"))
        with open(os.path.join(d, ".hidden", "x.md"), "w") as f:
            f.write("Brea interview hidden")
        self.dirs = [d]

    def tearDown(self):
        self.tmp.cleanup()

    def test_routing_and_off_the_bridge(self):
        for t in ("what do my notes say about the Brea interview", "search my notes for wigs",
                  "ask my notes when is Zoe's recital", "find rent in my notes",
                  "what did I write about the cake"):
            self.assertEqual(route_before_api(t), "notes_ask", t)
        self.assertNotIn("notes_ask", BRIDGE_ALLOW)
        self.assertEqual(route_before_api("take a note buy milk"), "note_take")

    def test_keyword_answer_names_the_file(self):
        line = ns.answer_from_notes("what do my notes say about the Brea interview", dirs=self.dirs, use_llm=False)
        self.assertTrue(line.startswith("In notes: Brea interview went well"), line)
        self.assertNotIn("secret", line)
        self.assertNotIn("hidden", line)

    def test_subfolder_and_possessive(self):
        line = ns.answer_from_notes("ask my notes when is Zoe's recital", dirs=self.dirs, use_llm=False)
        self.assertIn("In zoe: Zoe's recital is Friday at 6 pm", line)

    def test_nothing_found(self):
        self.assertEqual(ns.answer_from_notes("search my notes for tesla", dirs=self.dirs, use_llm=False),
                         ns.NOTES_NONE.format("tesla"))

    def test_llm_only_when_on_and_falls_back(self):
        seen = []
        line = ns.answer_from_notes("search my notes for rent", dirs=self.dirs, use_llm=True,
                                    ask=lambda q, h: seen.append((q, h)) or "Rent is due on the first.")
        self.assertEqual(line, "Rent is due on the first.")
        self.assertEqual(seen[0][0], "rent")
        line = ns.answer_from_notes("search my notes for rent", dirs=self.dirs, use_llm=True, ask=lambda q, h: None)
        self.assertIn("Rent is due on the 1st.", line)

    def test_flag_file_defaults_off(self):
        self.assertFalse(ns.llm_enabled(os.path.join(self.tmp.name, "missing.txt")))
        flag = os.path.join(self.tmp.name, "flag.txt")
        with open(flag, "w") as f:
            f.write("on\n")
        self.assertTrue(ns.llm_enabled(flag))

    def test_exports(self):
        self.assertIs(commands.answer_from_notes, ns.answer_from_notes)


if __name__ == "__main__":
    unittest.main()
