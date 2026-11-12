"""scripts/sign_local.sh: stable local signing. The suite blocks subprocess calls, so these tests read the script text.
The dry run (`scripts/sign_local.sh --dry-run`) is checked by hand and prints the plan without signing or using the keychain."""
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "sign_local.sh")


def _code(text):
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


class ScriptTextTests(unittest.TestCase):
    def setUp(self):
        with open(SCRIPT, encoding="utf-8") as handle:
            self.text = handle.read()
        self.code = _code(self.text)

    def test_it_is_an_executable_strict_bash_script(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        self.assertTrue(self.text.startswith("#!/bin/bash\n"))
        self.assertIn("set -euo pipefail", self.code)

    def test_it_never_touches_gatekeeper_or_passwords(self):
        for forbidden in ("spctl", "xattr", "quarantine", "sudo", "--deep", "unlock-keychain",
                          "set-key-partition-list", "find-generic-password", "add-trusted-cert", "defaults write"):
            self.assertNotIn(forbidden, self.code, forbidden)

    def test_the_requirement_pins_the_bundle_id_and_team_not_the_code_hash(self):
        self.assertIn('identifier \\"$BUNDLE_ID\\" and anchor apple generic and certificate leaf[subject.OU] = \\"$TEAM\\"',
                      self.code)
        self.assertNotIn("cdhash", self.code)
        self.assertIn('BUNDLE_ID="com.heyjev.app"', self.code)

    def test_the_team_id_comes_from_the_certificate_and_is_validated(self):
        self.assertIn("OU=", self.code)
        self.assertIn("{10}", self.code)
        self.assertIn("Could not read a 10-character team id", self.code)

    def test_it_signs_the_executable_then_the_bundle_and_verifies(self):
        self.assertLess(self.code.index('"${SIGN[@]}" "$EXE"'), self.code.index('"${SIGN[@]}" "$APP"'))
        self.assertIn("codesign --verify", self.code)

    def test_verify_does_not_use_strict_because_alias_builds_symlink_resources(self):
        self.assertNotIn("--strict", self.code)

    def test_dry_run_exits_before_any_signing(self):
        self.assertLess(self.code.index('if [ "$MODE" = "dry-run" ]'), self.code.index('"${SIGN[@]}" "$EXE"'))
        self.assertIn("nothing signed, no keychain use", self.code)

    def test_the_timestamp_server_is_not_used_so_local_signing_needs_no_network(self):
        self.assertIn("--timestamp=none", self.code)

    def test_a_missing_app_points_at_the_build_command(self):
        self.assertIn("py2app -A", self.code)


if __name__ == "__main__":
    unittest.main()
