"""Local test-results dashboard: static HTML report and browser open command.

A script runs pytest (`python -m commands.dashboard` or `python commands/dashboard.py`)
and writes `~/Library/Application Support/Hey Jev/test-report.html` with pass/fail
per command module and the last run time. Saying "show my test results" opens that
file in the default browser with `["open", path]`.

Mac-only. Not on the iPhone bridge allowlist. No listening socket or server,
no API keys, and no network calls.
"""
from datetime import datetime
import html
import os
import re
import subprocess
import sys

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "commands"

from . import config
from .shell import _run
from .textutil import _clean

OPENING_TEST_RESULTS = "Opening your test results."
MISSING_TEST_RESULTS = "Your test report isn't there yet."
FAILED_TEST_RESULTS = "I couldn't open your test results."
TEST_RESULTS_NOT_MAC = "Test results open on this Mac."

_PHRASE_RE = re.compile(
    rf"^{config._PLEASE}(?:hey\s+jev\b\s*,?\s+)?{config._PLEASE}"
    rf"(?:show(?:\s+me)?|open)\s+(?:(?:my|the)\s+)?test\s+(?:results?|report|dashboard)"
    rf"{config._TAIL}",
    re.I,
)

# Map test file stems (without leading `test_`) to their command module when the
# test filename uses a feature alias instead of the exact module filename.
COMMAND_MODULE_MAP = {
    "app_aliases": "apps",
    "used_apps": "apps",
    "brea_shift": "calendar_shift",
    "clipboard": "clipboard_history",
    "eta_home": "leave",
    "eta_work": "leave",
    "location_cache": "travel",
    "location_prompt": "travel",
    "outbox": "bridge",
    "sweep": "money",
    "videos_folder": "system",
    "hardware_guard": "system",
    "round2": "routing",
    "mini_bar": "mini_bar",
    "pill_collapse": "mini_bar",
    "pill_key": "mini_bar",
    "mic_level": "dictation",
    "window_layout": "assistant_layout",
}

_VERBOSE_LINE_RE = re.compile(
    r"^\s*(?:[\w./\\-]+/)?(?P<file>test_[A-Za-z0-9_]+\.py)::.+?\s+"
    r"(?P<status>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)(?:\s+\(.*\))?(?:\s+\[\s*\d+%\])?\s*$"
)
# Collection errors (import or syntax error in a test file) abort before any
# per-test lines, e.g. "ERROR tests/test_bad.py" or "ERROR tests/test_bad.py - ...".
_COLLECT_ERROR_RE = re.compile(
    r"^\s*ERROR\s+(?:[\w./\\-]+/)?(?P<file>test_[A-Za-z0-9_]+\.py)(?:\s+-\s+.*)?\s*$"
)
_DOT_LINE_RE = re.compile(
    r"^\s*(?:[\w./\\-]+/)?(?P<file>test_[A-Za-z0-9_]+\.py)\s+"
    r"(?P<dots>[.FEesxX]+)(?:\s+\[\s*\d+%\])?\s*$"
)


def is_test_results_phrase(text):
    """True for 'show my test results' and close open/show report variants."""
    raw = _clean(text or "").strip()
    return bool(raw) and bool(_PHRASE_RE.match(raw))


def report_path(path=None):
    """Absolute path to test-report.html. Does not invoke a shell."""
    raw = config.TEST_REPORT_PATH if path is None else path
    if not isinstance(raw, str):
        return ""
    text = raw.strip()
    if not text or "\x00" in text or "\n" in text or "\r" in text:
        return ""
    expanded = os.path.expanduser(text)
    if not expanded or expanded.startswith("~"):
        return ""
    target = os.path.abspath(expanded)
    if not target.startswith("/"):
        return ""
    return target


def open_report_args(target):
    """['open', target]. Refuses a string command or relative path."""
    if not isinstance(target, str) or not target.startswith("/"):
        raise TypeError("open takes an absolute path in an argument list")
    return ["open", target]


def module_for_test_file(filename):
    """Command module name for a test file such as tests/test_notes_search.py."""
    base = os.path.basename(str(filename or "").strip())
    if base.endswith(".py"):
        base = base[:-3]
    stem = base[5:] if base.startswith("test_") else base
    if not stem:
        return "unknown"
    return COMMAND_MODULE_MAP.get(stem, stem)


def parse_pytest_output(output):
    """Return sorted per-module pass/fail summaries from pytest stdout."""
    by_module = {}

    def _record(test_file, passed=0, failed=0, skipped=0):
        mod = module_for_test_file(test_file)
        base = os.path.basename(test_file)
        entry = by_module.get(mod)
        if entry is None:
            entry = {
                "module": mod,
                "files": [],
                "passed": 0,
                "failed": 0,
                "skipped": 0,
            }
            by_module[mod] = entry
        if base and base not in entry["files"]:
            entry["files"].append(base)
        entry["passed"] += int(passed)
        entry["failed"] += int(failed)
        entry["skipped"] += int(skipped)

    for line in str(output or "").splitlines():
        m = _VERBOSE_LINE_RE.match(line)
        if m:
            status = m.group("status")
            test_file = m.group("file")
            if status in ("PASSED", "XFAIL", "XPASS"):
                _record(test_file, passed=1)
            elif status in ("FAILED", "ERROR"):
                _record(test_file, failed=1)
            elif status == "SKIPPED":
                _record(test_file, skipped=1)
            continue
        c = _COLLECT_ERROR_RE.match(line)
        if c:
            _record(c.group("file"), failed=1)
            continue
        d = _DOT_LINE_RE.match(line)
        if d:
            test_file = d.group("file")
            dots = d.group("dots")
            passed = sum(1 for ch in dots if ch in (".", "x", "X"))
            failed = sum(1 for ch in dots if ch in ("F", "E"))
            skipped = sum(1 for ch in dots if ch == "s")
            _record(test_file, passed=passed, failed=failed, skipped=skipped)

    results = []
    for mod in sorted(by_module):
        item = by_module[mod]
        item["files"] = sorted(item["files"])
        if item["failed"] > 0:
            item["status"] = "FAIL"
        elif item["passed"] > 0:
            item["status"] = "PASS"
        elif item["skipped"] > 0:
            item["status"] = "SKIP"
        else:
            item["status"] = "FAIL"
        results.append(item)
    return results


def format_run_time(now=None):
    """Human-readable local timestamp for the report."""
    if isinstance(now, str) and now.strip():
        return now.strip()
    if isinstance(now, (int, float)):
        dt = datetime.fromtimestamp(now).astimezone()
    elif isinstance(now, datetime):
        dt = now if now.tzinfo is not None else now.astimezone()
    else:
        dt = datetime.now().astimezone()
    tz = dt.tzname() or "local"
    return "{0} {1}".format(dt.strftime("%Y-%m-%d %H:%M:%S"), tz)


def render_report_html(modules, ran_at=None, returncode=0):
    """Static HTML document showing pass/fail per command module and last run time."""
    items = list(modules or [])
    stamp = format_run_time(ran_at)
    total_passed = sum(int(m.get("passed", 0)) for m in items)
    total_failed = sum(int(m.get("failed", 0)) for m in items)
    all_ok = (returncode == 0) and bool(items) and all(m.get("status") in ("PASS", "SKIP") for m in items)
    overall = "PASS" if all_ok else "FAIL"
    overall_class = "pass" if all_ok else "fail"

    rows = []
    for m in items:
        mod = str(m.get("module") or "")
        files = ", ".join(m.get("files") or ())
        passed = int(m.get("passed", 0))
        failed = int(m.get("failed", 0))
        status = m.get("status") if m.get("status") in ("PASS", "SKIP") else "FAIL"
        cls = status.lower()
        rows.append(
            "<tr class=\"row-{cls}\">"
            "<td><code>{mod}</code></td>"
            "<td class=\"files\">{files}</td>"
            "<td><span class=\"badge {cls}\">{status}</span></td>"
            "<td class=\"num\">{passed}</td>"
            "<td class=\"num\">{failed}</td>"
            "</tr>".format(
                cls=cls,
                mod=html.escape(mod),
                files=html.escape(files),
                status=status,
                passed=passed,
                failed=failed,
            )
        )
    if not rows:
        rows.append(
            "<tr class=\"row-fail\"><td colspan=\"5\">No test results collected.</td></tr>"
        )

    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Hey Jev Test Results</title>
<style>
body {{
  margin: 0;
  padding: 32px 24px 48px;
  background: #f6f4ef;
  color: #1c1b19;
  font: 15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}}
main {{ max-width: 880px; margin: 0 auto; }}
header {{
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
}}
h1 {{ font-size: 24px; margin: 0; }}
.meta {{ color: #5c574e; font-size: 14px; }}
.summary {{
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}}
.card {{
  background: #fff;
  border-radius: 10px;
  padding: 12px 16px;
  min-width: 120px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}}
.card .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #6d675e; }}
.card .value {{ font-size: 20px; font-weight: 600; margin-top: 2px; }}
table {{
  width: 100%;
  border-collapse: collapse;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}}
th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #ede9e0; }}
th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: #6d675e; background: #faf8f4; }}
tr:last-child td {{ border-bottom: none; }}
td.files {{ color: #5c574e; font-size: 13px; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}}
.badge.pass, .value.pass {{ background: #e3f5e8; color: #166534; }}
.badge.fail, .value.fail {{ background: #fde8e8; color: #991b1b; }}
.badge.skip, .value.skip {{ background: #efede8; color: #57534e; }}
</style>
</head>
<body>
<main>
<header>
  <h1>Hey Jev Test Results</h1>
  <div class="meta" id="last-run">Last run: {last_run}</div>
</header>
<section class="summary">
  <div class="card"><div class="label">Overall</div><div class="value"><span class="badge {overall_class}">{overall}</span></div></div>
  <div class="card"><div class="label">Modules</div><div class="value">{module_count}</div></div>
  <div class="card"><div class="label">Passed</div><div class="value">{total_passed}</div></div>
  <div class="card"><div class="label">Failed</div><div class="value">{total_failed}</div></div>
</section>
<table>
  <thead>
    <tr>
      <th>Command Module</th>
      <th>Test Suite</th>
      <th>Status</th>
      <th class="num">Passed</th>
      <th class="num">Failed</th>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>
</main>
</body>
</html>
""".format(
        last_run=html.escape(stamp),
        overall=overall,
        overall_class=overall_class,
        module_count=len(items),
        total_passed=total_passed,
        total_failed=total_failed,
        rows="\n    ".join(rows),
    )


def write_test_report(html_text, path=None):
    """Atomically write the HTML report to disk and return its path."""
    target = report_path(path)
    if not target:
        raise ValueError("invalid test report path")
    folder = os.path.dirname(target)
    if folder:
        os.makedirs(folder, exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(str(html_text or ""))
    os.replace(tmp, target)
    return target


def pytest_command(python_executable=None):
    """Argument list to run pytest in verbose mode. Never a shell string."""
    exe = python_executable or sys.executable or "python3"
    return [exe, "-m", "pytest", "-v", "--tb=no"]


def run_pytest(runner=None, root=None, python_executable=None):
    """Run pytest and return (returncode, combined_output)."""
    repo_root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = pytest_command(python_executable)
    run_fn = subprocess.run if runner is None else runner
    proc = run_fn(cmd, cwd=repo_root, capture_output=True, text=True)
    out = (getattr(proc, "stdout", "") or "") + "\n" + (getattr(proc, "stderr", "") or "")
    code = int(getattr(proc, "returncode", 0) or 0)
    return code, out


def build_test_report(path=None, runner=None, now=None, root=None, python_executable=None):
    """Run pytest, render the static HTML report, and write it to `path`."""
    code, output = run_pytest(runner=runner, root=root, python_executable=python_executable)
    modules = parse_pytest_output(output)
    stamp = format_run_time(now)
    html_text = render_report_html(modules, ran_at=stamp, returncode=code)
    written = write_test_report(html_text, path=path)
    return {
        "path": written,
        "returncode": code,
        "ran_at": stamp,
        "modules": modules,
    }


def open_test_results(path=None, platform=None, exists=None, run=None):
    """Open test-report.html in the default browser on macOS. Does not create it."""
    if (sys.platform if platform is None else platform) != "darwin":
        return TEST_RESULTS_NOT_MAC
    target = report_path(path)
    check = os.path.isfile if exists is None else exists
    try:
        found = bool(target) and not os.path.islink(target) and bool(check(target))
    except OSError:
        found = False
    if not found:
        return MISSING_TEST_RESULTS
    runner = _run if run is None else run
    try:
        runner(open_report_args(target))
    except Exception:
        return FAILED_TEST_RESULTS
    return OPENING_TEST_RESULTS


def main(argv=None):
    """CLI entry point: run pytest and write the static HTML report."""
    out_path = argv[0] if argv else None
    result = build_test_report(path=out_path)
    print(result["path"])
    return result["returncode"]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
