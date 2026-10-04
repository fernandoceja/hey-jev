"""Read-only check for commits on the upstream Hey Jev repo.

One HTTPS GET, and only when the owner clicks Check for updates. The request
is the public GitHub compare API, with no token. The triple-dot compare of
fernandoceja:main...main on henryklunaris/hey-jev is the merge-base of the
fork's main with upstream main. The commits in that response are the ones
upstream has that this fork's main does not. Nothing is stored, downloaded,
or applied.
"""
import json
import urllib.error
import urllib.request

TIMEOUT = 10
UPSTREAM = "henryklunaris/hey-jev"
FORK_OWNER = "fernandoceja"
API_URL = "https://api.github.com/repos/henryklunaris/hey-jev/compare/fernandoceja:main...main"
COMPARE_PAGE = "https://github.com/henryklunaris/hey-jev/compare/fernandoceja:main...main"
_API_PREFIX = "https://api.github.com/"

UP_TO_DATE = "Up to date"
NETWORK_MESSAGE = "Couldn't reach GitHub. Check the network and try again."
RATE_MESSAGE = "GitHub rate limit. Try again in a minute."
HTTP_MESSAGE = "GitHub couldn't compare the repos."
PARSE_MESSAGE = "Couldn't read GitHub's reply."


def api_url():
    return API_URL


def compare_page_url():
    return COMPARE_PAGE


def _failure(kind, message):
    return {"kind": kind, "title": "Couldn't check", "body": message, "open_url": ""}


def _current():
    return {
        "kind": "current",
        "title": UP_TO_DATE,
        "body": "Hey Jev matches henryklunaris/hey-jev main.",
        "open_url": COMPARE_PAGE,
    }


def _commit_line(item):
    """Short sha, date, and the first line of the message. No patch."""
    if not isinstance(item, dict):
        return None
    sha = str(item.get("sha") or "").strip()
    if not sha:
        return None
    commit = item.get("commit") if isinstance(item.get("commit"), dict) else {}
    message = str(commit.get("message") or "")
    first = message.splitlines()[0] if message else ""
    title = " ".join(first.split()) or "(no message)"
    if len(title) > 120:
        title = title[:117] + "..."
    author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
    raw_date = str(author.get("date") or "")
    date = raw_date[:10] if len(raw_date) >= 10 and raw_date[4] == "-" else ""
    return {"sha": sha[:7], "date": date, "title": title}


def interpret(status, body):
    """Turn one compare response into the sheet. `status` is the HTTP code."""
    try:
        code = int(status)
    except (TypeError, ValueError):
        code = 0
    if code in (403, 429):
        return _failure("rate_limit", RATE_MESSAGE)
    if code != 200:
        return _failure("error", HTTP_MESSAGE)
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return _failure("error", PARSE_MESSAGE)
    if not isinstance(data, dict):
        return _failure("error", PARSE_MESSAGE)
    commits = []
    for item in data.get("commits") or []:
        line = _commit_line(item)
        if line is not None:
            commits.append(line)
    try:
        ahead = int(data.get("ahead_by"))
    except (TypeError, ValueError):
        ahead = len(commits)
    if ahead <= 0:
        return _current()
    shown = commits[:ahead] if ahead < len(commits) else commits
    lines = []
    for item in shown:
        when = item["date"] or "undated"
        lines.append(f"{item['sha']}  {when}  {item['title']}")
    try:
        total = int(data.get("total_commits"))
    except (TypeError, ValueError):
        total = ahead
    if total > len(shown) or not shown:
        lines.append("The compare page lists the rest.")
    noun = "commit" if ahead == 1 else "commits"
    return {
        "kind": "updates",
        "title": f"{ahead} new {noun} on henryklunaris/hey-jev",
        "body": "\n".join(lines),
        "open_url": COMPARE_PAGE,
    }


def check_upstream(fetch=None, timeout=TIMEOUT):
    """One GET. `fetch(url, timeout)` returns (status, body) or raises."""
    fetch = fetch or http_get
    try:
        status, body = fetch(api_url(), timeout)
    except Exception:
        return _failure("network", NETWORK_MESSAGE)
    return interpret(status, body)


def http_get(url, timeout):
    """GET a public api.github.com URL. No auth header and no body."""
    if not str(url).startswith(_API_PREFIX):
        raise ValueError("refusing a request that is not to api.github.com")
    request = urllib.request.Request(
        url,
        data=None,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hey-jev",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            code = getattr(response, "status", None)
            if code is None:
                code = response.getcode()
            return int(code), raw.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        return int(exc.code), raw.decode("utf-8", "replace")


def safe_browser_url(url):
    """The compare page, or empty. The sheet will not open any other address."""
    if str(url) == COMPARE_PAGE:
        return COMPARE_PAGE
    return ""
