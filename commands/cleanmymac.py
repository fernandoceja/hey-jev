"""Open CleanMyMac and start a Smart Care scan. Mac-only. SCAN ONLY.

Jev never cleans, removes, or runs Smart Care tasks. It opens the app,
selects Smart Care, and presses the button named exactly "Scan". Results
stay on screen for Fernando to review; "Run", "Clean", and "Remove" are
never clicked.

MacPaw documents no URL scheme or AppleScript dictionary for starting a
scan, so the scan is started with System Events UI scripting, which uses
Jev's existing Accessibility permission. If that fails, Jev opens the app
and says to press Scan.

Not in BRIDGE_ALLOW, so the iPhone bridge cannot start it. Nothing here
binds or listens, reads the Keychain, or touches the bridge. Commands are
argument lists, never shell strings.
"""
import os
import re
import sys

from .shell import _run

# Current CleanMyMac (2024+, "CleanMyMac" / CleanMyMac_5.app) first, then
# CleanMyMac X. Setapp builds use the same bundle ids with a -setapp suffix.
CLEANMYMAC_APPS = (
    ("/Applications/CleanMyMac_5.app", "com.macpaw.CleanMyMac5"),
    ("/Applications/CleanMyMac.app", "com.macpaw.CleanMyMac5"),
    ("/Applications/CleanMyMac 5.app", "com.macpaw.CleanMyMac5"),
    ("~/Applications/CleanMyMac_5.app", "com.macpaw.CleanMyMac5"),
    ("~/Applications/CleanMyMac.app", "com.macpaw.CleanMyMac5"),
    ("/Applications/Setapp/CleanMyMac.app", "com.macpaw.CleanMyMac5-setapp"),
    ("/Applications/CleanMyMac X.app", "com.macpaw.CleanMyMac4"),
    ("~/Applications/CleanMyMac X.app", "com.macpaw.CleanMyMac4"),
    ("/Applications/Setapp/CleanMyMac X.app", "com.macpaw.CleanMyMac4-setapp"),
)

CMM_NOT_MAC = "CleanMyMac scans run on this Mac."
CMM_NOT_INSTALLED = "CleanMyMac isn't installed on this Mac."
CMM_FAILED = "I couldn't open CleanMyMac."
CMM_SCANNING = ("Starting a CleanMyMac Smart Care scan. It's scan only. "
                "Review the results before you clean anything.")
CMM_ALREADY = "CleanMyMac is already scanning. Review the results when it's done."
CMM_PRESS_SCAN = ("I opened CleanMyMac to Smart Care, but I couldn't press Scan. "
                  "Press Scan to start. Nothing gets cleaned unless you choose it.")

# The only button Jev may press. Never Run, Clean, Remove, or Start Over.
SCAN_BUTTON = "Scan"
FORBIDDEN_BUTTONS = ("Run", "Clean", "Remove", "Start Over", "Uninstall", "Delete")

# argv: bundle id. Returns "scanning", "already", "nowindow", or "noscan".
SMART_CARE_SCRIPT = r'''
on run argv
    set bid to item 1 of argv
    tell application id bid to activate
    tell application "System Events"
        set p to missing value
        repeat 60 times
            try
                set p to first application process whose bundle identifier is bid
                if (count of windows of p) > 0 then exit repeat
            end try
            delay 0.25
        end repeat
        if p is missing value then return "nowindow"
        if (count of windows of p) = 0 then return "nowindow"
        set frontmost of p to true
        set w to window 1 of p
        try
            set els to entire contents of w
        on error
            return "noscan"
        end try
        repeat with e in els
            try
                if (name of e as text) is "Smart Care" or (description of e as text) is "Smart Care" then
                    click e
                    exit repeat
                end if
            end try
        end repeat
        delay 1
        set els to entire contents of window 1 of p
        repeat with e in els
            try
                if role of e is "AXButton" then
                    set n to ""
                    try
                        set n to name of e as text
                    end try
                    if n is "missing value" or n is "" then set n to description of e as text
                    if n is "Stop" then return "already"
                    if n is "Scan" then
                        click e
                        return "scanning"
                    end if
                end if
            end try
        end repeat
    end tell
    return "noscan"
end run
'''

_LEAD = r"^(?:(?:hey\s+)?jev\b[\s,]*)?(?:(?:please|can\s+you|could\s+you|let'?s|i\s+want\s+to|go\s+ahead\s+and)\s+)*"
# "CleanMyMac", "clean my mac", "clean mymac", "cleanmy mac", "clean my mack", "clean my max".
_CMM = r"(?:clean\s*my\s*ma(?:c|ck|cs|x|k)|cleanmymac(?:\s*(?:x|5|five))?|clean\s*my\s*mac\s*(?:x|5|five))"
_SCAN_WORDS = r"(?:scan|smart\s+care|smart\s+care\s+scan|check|checkup|check\s+up)"
_PHRASES = tuple(re.compile(alt) for alt in (
    r"(?:(?:run|start|do|launch|use)\s+(?:a\s+|the\s+)?(?:full\s+)?)?" + _CMM
    + r"(?:\s+(?:full\s+)?" + _SCAN_WORDS + r")?",
    r"(?:run|start|do)\s+(?:a\s+|the\s+)?(?:full\s+)?(?:" + _CMM + r"\s+)?smart\s+care(?:\s+scan)?",
    r"(?:run\s+)?(?:a\s+)?(?:full\s+)?scan\s+(?:of\s+|on\s+)?my\s+(?:mac|computer|laptop)"
    r"(?:\s+with\s+" + _CMM + r")?",
    r"(?:run\s+)?(?:a\s+)?(?:full\s+)?(?:mac|storage)\s+scan",
    r"smart\s+care(?:\s+scan)?",
))


def _norm(text):
    raw = (text or "").lower().replace("\u2019", "'")
    raw = re.sub(r"[^a-z0-9' ]+", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def _strip(text):
    t = re.sub(_LEAD, "", _norm(text))
    t = re.sub(r"\s+(?:please|now|for me)$", "", t)
    return t.strip()


def is_cleanmymac_phrase(text):
    """True for "run CleanMyMac", "CleanMyMac scan", "scan my Mac", "clean my Mac".

    "open CleanMyMac" is left to the plain open-app command. "clean up" and
    "clean my room" do not match.
    """
    t = _strip(text)
    return bool(t) and any(rx.fullmatch(t) for rx in _PHRASES)


def find_cleanmymac(exists=os.path.exists):
    """(path, bundle id) of the first CleanMyMac on disk, or ("", "")."""
    for raw, bundle in CLEANMYMAC_APPS:
        path = os.path.abspath(os.path.expanduser(raw))
        if exists(path):
            return path, bundle
    return "", ""


def start_scan(platform=None, exists=os.path.exists, run=None):
    """Open CleanMyMac, select Smart Care, press Scan. Never cleans."""
    if (sys.platform if platform is None else platform) != "darwin":
        return CMM_NOT_MAC
    runner = run or _run
    path, bundle = find_cleanmymac(exists)
    if not path:
        return CMM_NOT_INSTALLED
    try:
        runner(["open", path])
    except Exception:
        return CMM_FAILED
    try:
        out = runner(["osascript", "-e", SMART_CARE_SCRIPT, bundle], timeout=30)
    except Exception:
        return CMM_PRESS_SCAN
    result = (out if isinstance(out, str) else getattr(out, "stdout", "") or "").strip()
    if result == "scanning":
        return CMM_SCANNING
    if result == "already":
        return CMM_ALREADY
    return CMM_PRESS_SCAN


def start_scan_from_text(_text, platform=None, exists=os.path.exists, run=None):
    return start_scan(platform=platform, exists=exists, run=run)
