# Jev cleanup: bring Eney's Mac cleanup into Jev

Status: **implementation in progress on `jev/cleanup-all`, delivered as one PR.**

Goal: Jev does everything Eney's Mac cleanup did, in Jev's own style, so Fernando can uninstall Eney and Setapp.

What Eney did on this Mac on Nov 10 2026 (from Fernando): it scanned the SSD, sorted the findings into "safe to delete", "your call" and "apps you could remove", then removed only the safe items (about 0.7 GB) after Fernando approved.

## Planner's notes: read these first

1. **The three REA study notes were not readable when this plan was written.** They live only on the Mac (`~/Documents/Fernando Ceja/Developer/AI-Projects/REA/Requests/`: "how-eney-cleans-the-mac…", "eney-mac-cleanup-narrowed-to-two-areas…", "eney-full-capability-inventory…"). The plan was written in a cloud session that had the repo but not that folder. The inventory in section 1 is built from Fernando's brief and from Jev's code. **PR 0 reconciles it against the notes on the Mac before any build PR starts.** Rows that came only from the brief are marked "Brief".
2. **Jev already has more than half of this.** PR #112 added a storage scan, an approval gate that only uses the Trash, an undo, and an audit log (`commands/storage_scan.py`, `commands/cleanup_gate.py`, `commands/storage_scan_ui.py`). PR #96 added the Downloads and Desktop report (`commands/tidy_downloads.py`). This plan extends those. Nothing is restarted.
3. **The shipped storage card breaks two of the hard rules today.** PR 1 fixes both before anything else is built:
   - `~/.cache/huggingface` (Jev's models) is listed as `ask_first` with `deletable=True`, so its checkbox is live. The gate's protected list doesn't cover `~/.cache`.
   - Xcode DerivedData is one row marked `safe` and ticked by default. If the Luigi's Mansion, High On Life or DmIOS builds live in DerivedData, one click would send them to the Trash.
   Until PR 1 merges, treat the Storage Scan card as look-only.
4. **Moving something to the Trash doesn't free space.** Space comes back only when the Trash is emptied. The "before and after" numbers in PR 5 say so plainly, and emptying the Trash is a separate step with its own confirm (decision D2).

---

## Executive summary

1. **Safety first, then scan, then act.** PR 1 puts every hard rule into one tested module that both the scan and the gate use. Each new area gets a scan PR before its act PR.
2. **Twelve small PRs** (PR 0 to PR 11): reconcile notes, safety floor, three scan PRs, the three-bucket screen, act with before/after and log, then apps (scan, leftovers, remove), then iCloud (scan, make cloud-only), then the switch-over.
3. **Fernando can remove Eney after PR 11** and the checklist in section 9. Jev never uninstalls Eney or Setapp itself. That step is his.

## Decisions for Fernando (recommendations only, nothing is decided)

| # | Question | Recommendation | Where it lands |
|---|---|---|---|
| D1 | The repo has `.github/workflows/tests.yml`. | Delete all workflows in this PR. No workflow is added, run, awaited, or triggered. | All PRs |
| D2 | Trash moves don't free space until the Trash is emptied. | Jev shows a Trash summary and opens Trash in Finder. Fernando can empty it manually in Finder. | PR 5 |
| D3 | When is an app "unused"? | Not opened in 90 days, or never opened. One constant, `UNUSED_APP_DAYS = 90`. | PR 6 |
| D4 | Which iCloud files are worth offering? | 50 MB or larger, fully uploaded, not opened or changed in 30 days. | PR 9 |
| D5 | The "Mac health" chip and the sidebar "Mac" row run a CleanMyMac scan. If CleanMyMac is a Setapp copy, it stops working when Setapp goes. | PR 11 points the chip and the sidebar row at Jev's own cleanup. The "CleanMyMac Scan" Quick Command stays as it is. | PR 11 |
| D6 | Where do the real protected paths live? | In a local file on the Mac that is never committed, `~/Library/Application Support/Hey Jev/cleanup-protected.json`. The repo holds name patterns and an example file only. | PR 0, PR 1 |
| D7 | Simulators (`~/Library/Developer/CoreSimulator`) are deletable in today's card. | Report-only and list under "Fernando does this" (Xcode manages it). | PR 1 |

---

PR 0 reconciliation: the three REA request notes cover storage/System Data cleanup (caches, logs, backups, development data, attachments, snapshots), large and old files, app age/size/last-opened and leftovers, plus startup/login items and memory/RAM actions. The storage and app areas are mapped to PRs 1–11 below. Startup/login item management, memory freeing, malware checks, and general AI-driven actions that change the system remain out of scope; no helper or privileged operation is introduced. The broad inventory note is a catalog request, not authorization to add unrelated features.

## 1. Feature inventory

Source: "Brief" is Fernando's Nov 10 description. "Notes" means the row must be confirmed against the REA notes in PR 0. Nothing here is taken from Eney's code, assets or wording.

| # | Eney cleanup feature | Source | Jev today | Missing | PR |
|---|---|---|---|---|---|
| 1 | Scan the SSD and total the sizes | Brief | **Partly.** `storage_scan.scan()` measures a fixed list of folders on a background thread, can be cancelled, and flags partial measurements. | New areas (rows 8, 10–14). | 2, 3, 6, 7, 9 |
| 2 | Sort into "safe to delete", "your call", "apps you could remove" | Brief | **No.** One flat list with a `safe` / `ask_first` / `leave_alone` word on each row. | The three-bucket screen. | 4 |
| 3 | Remove only after approval | Brief | **Yes.** `CleanupGate`: one visible card, a click-only approval, a single-use token, and a re-check right before each move. | One refused item aborts the whole batch. No confirm sheet that lists the items and the total. | 5 |
| 4 | User caches (`~/Library/Caches`) | Brief | **Yes**, one row per cache folder. | Nothing new. Gets the plain reasons from PR 2. | 2 |
| 5 | Logs (`~/Library/Logs`) | Brief | **Yes**, as one row. | One row per log folder. | 2 |
| 6 | Xcode DerivedData | Brief | **Yes, but as one lump marked safe.** | One row per project, with the protected build folders left alone. | 1 |
| 7 | Xcode DeviceSupport | Brief | **Yes** for iOS. | One row per OS version. Add watchOS and tvOS DeviceSupport. | 2 |
| 8 | npm, pip and Homebrew caches | Brief | **Partly.** pip and Homebrew sit under `~/Library/Caches`, so they show up as unnamed cache rows. npm (`~/.npm/_cacache`) is not scanned. | Named rows with a plain reason. No `npm`, `pip` or `brew` command is run. | 2 |
| 9 | Trash | Brief | **Report only.** The Trash row is `leave_alone`. A separate spoken "empty the trash" exists with a yes/no confirm. | Trash size in "your call" with the D2 button. | 2, 5 |
| 10 | Large or old Downloads | Brief | **Partly.** `tidy_downloads` gives a text report (old installers, duplicates, large files). The storage scan lists `.dmg`, `.pkg`, `.ipsw`. | Rows in the review screen. Active downloads excluded. | 3 |
| 11 | Unused apps with sizes and last-used dates | Brief | **No.** `commands/apps.py` indexes installed apps and reads bundle ids. | Size, last-used date, the "unused" test. | 6 |
| 12 | Remove an app together with its leftovers | Brief | **No.** | Leftover finder and the app remove flow. | 7, 8 |
| 13 | Leftovers in `~/Library` from apps that are gone (Application Support, Containers, Group Containers) | Brief | **No.** | Orphan finder. Always "your call". | 7 |
| 14 | iCloud items that are already uploaded, made cloud-only | Brief | **No.** | iCloud scan and the make-cloud-only action. | 9, 10 |
| 15 | Free space before and after | Brief | **Before only.** The card shows free space when the scan ends. | The after number, with the Trash caveat. | 5 |
| 16 | A log of what was removed | Brief | **Kept but hidden.** `cleanup-audit.jsonl` records every propose, approve, refuse, move and restore. | A readable log on screen. | 5 |
| 17 | Low-disk nudge | Bubble v2 notes (`outOfDiscSpace` reaction) | **Yes.** The orb's `low_disk` reaction highlights the Mac health chip. | The chip opens CleanMyMac, not Jev's cleanup. | 11 |
| 18 | Startup/login-item management, memory/RAM freeing, malware checks, and AI-driven system changes | Notes | Not part of the existing storage scan | Not covered; kept out of scope for this cleanup | — |

**Jev already does these and Eney's brief doesn't mention them** (kept as they are): undo after a move; a 24-hour "recently changed" refusal; Xcode Archives, iOS backups (marked irreplaceable), Mail and Messages attachments (size only), Ollama models, and Time Machine local snapshots (listed, never touched).

**Not planned** unless PR 0 finds it in the notes and Fernando asks: anything that needs admin rights, system caches under `/Library` or `/System`, memory "free-up" tricks, login-item managers, malware scans.

---

## 2. Rules every PR follows

### Hard rules (copied word for word into every Codex prompt)

```
HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.
```

### How the rules become code (PR 1)

One pure module, `commands/cleanup_rules.py`, answers "may Jev touch this path?" The scan uses it to choose a bucket and the gate uses it again right before any move. A path is **protected** (listed at most, never actionable) when any of these is true:

| Rule | Test |
|---|---|
| Jev's models | The path is `~/.cache` or inside it. |
| Developer work | The path is `~/Developer` or inside it, or any ancestor folder contains `.git`. This is stricter than the rule asks: all of `~/Developer` is off limits, repo or not. |
| Named projects | Any path component matches, ignoring case, spaces and punctuation: `voicestudio`, `luigi`, `highonlife`, `dmios`, `jarvis`. This also covers DerivedData subfolders such as `DmIOS-abc123`. |
| Xcode itself | Any component is `Xcode.app` or matches `Xcode*.app`, plus `~/Library/Developer/Xcode/UserData`. |
| Active downloads | The name ends in `.download`, `.crdownload`, `.part` or `.partial`, or the item is inside such a bundle. |
| Databases | The item is, or contains, a file named `NoteStore.sqlite` or `omnivoice.db`: protected. Any other `*.db`, `*.sqlite`, `*.sqlite3`, `*.sqlite-wal`, `*.sqlite-shm` outside `~/Library/Caches`: the item can never be "safe", and its row says "contains a database (size only)". The check is by file name from `scandir`. Nothing is opened. |
| Jev itself | `~/Library/Application Support/Hey Jev`, the running app bundle, and `~/Documents/.cos-tmp`. |
| Eney and Setapp | `/Applications/Setapp`, `/Applications/Eney.app` (already in the gate). Listed under "Fernando does this". |
| Outside home, or system | Anything not under the home folder, plus the gate's existing system list. |
| Local extras | Any path listed in `~/Library/Application Support/Hey Jev/cleanup-protected.json` (D6). |

A path is **"Fernando does this"** (listed with a one-line how-to, never actionable) when it is owned by another user, its parent folder isn't writable by Fernando, or it sits outside the home folder. Jev never asks for a password and never retries with more rights.

### The four places a finding can land

| Bucket | What goes in | Ticked by default |
|---|---|---|
| **Safe to delete** | Things macOS or a tool rebuilds by itself: cache folders, log folders, DerivedData for unprotected projects, DeviceSupport, npm / pip / Homebrew caches. Only when not changed in the last 24 hours, fully measured, no symlinks inside, and no database outside `~/Library/Caches`. | Yes |
| **Your call** | Things only Fernando can judge: large or old Downloads, old installers, possible duplicates, Xcode Archives, iOS backups (marked irreplaceable), Ollama models, leftovers from apps that are gone, the Trash, and iCloud files that can be made cloud-only. | No |
| **Remove apps** | Apps not opened in 90 days, each with its size, last-used date and leftovers. | No |
| **Left alone** (a collapsed list under the three buckets) | Protected paths with their size and the reason, and the "Fernando does this" items with a how-to. No checkboxes. | — |

### Tests and the fake home

- `tests/fake_home.py` (new in PR 1) builds a fake home under pytest's `tmp_path`: caches, logs, DerivedData with a `DmIOS-xyz` project and a plain project, `.cache/huggingface`, a `Developer/some-repo/.git`, a `VoiceStudio` folder, a `Downloads` folder with a `.download` bundle, an `Application Support` folder holding a `data.sqlite`, `NoteStore.sqlite` in a group container, and files dated with `os.utime`. Every scan and gate test runs against it.
- The existing `tests/mac_guard.py` already makes any real subprocess fail a test, so every `mdls`, `brctl` and `osascript` call must go through an injected runner.
- A source test in each PR asserts the cleanup modules contain no `os.remove`, `shutil.rmtree`, `.unlink(`, `rm -`, `sqlite3`, and no `open(` in the scan modules (extends `test_no_permanent_removal_code`).
- Local run on the Mac, from the repo's Python 3.9 venv:

```bash
cd ~/Developer/hey-jev && mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup"
```

- Hand tests that move anything use a throwaway home first. PR 4 adds `JEV_CLEANUP_HOME`: when it points inside `~/Documents/.cos-tmp`, the card scans that folder as if it were home. Any other value is ignored. `scripts/make_cleanup_fake_home.py` builds one.

### Base checks (in every PR's hand test)

- [ ] B1. Local pytest is green and the PR body pastes the last line of the run.
- [ ] B2. Jev launches to Ready. Voice, typing and the orb work as before.
- [ ] B3. Quick Commands → Storage Scan opens and finishes. Nothing is moved by opening it.
- [ ] B4. With Zoe mode on, the cleanup screen doesn't open.
- [ ] B5. `~/.cache`, VoiceStudio, Xcode and the named build folders show under "Left alone" (or not at all), never with a checkbox.

---

## 3. Design

### Scan

- Everything is `lstat` and `scandir`. No file is opened, hashed or read. This also keeps iCloud files from downloading during a scan.
- Sizes are allocated bytes (`st_blocks`), so an iCloud file that is already cloud-only counts as zero.
- One walk per item collects the size, the newest change time, whether a symlink was seen, and whether a database file name was seen. The gate still repeats its own check before a move.
- Bounded and cancellable, as today (`limit`, `cancel`).
- Every row carries a **plain reason** in Jev's words, for example: "Apps rebuild this by themselves." / "Xcode rebuilds this the next time you build that project." / "Installer for an app you already have, 7 months old." / "Not opened since March 2." Reasons live in one table in `cleanup_rules.py`.

### Review screen

- Lives in the full Jev window, where the storage card is now. Native AppKit, Jev's palette and type from `full_window.PALETTE`. No layout, icon or wording taken from Eney.
- Header: free space now, plus "Scan again".
- Three sections with a count and total each: **Safe to delete**, **Your call**, **Remove apps**. Then the collapsed **Left alone** list.
- Each row: checkbox, name, size in human units (`tidy_downloads.human_size`), the plain reason, and the path in small type. A row Jev can't act on is greyed with the reason ("Changed in the last 24 hours", "Needs permission", "Fernando does this: …").
- Footer: "Selected: 14 items, 1.2 GB" and one button, "Review and move to Trash…". Nothing happens on that click except opening the confirm sheet.
- Click-only, like today. No voice or typed phrase can approve a move. Not on the iPhone bridge. Refused in Zoe mode.

### Act

- **Confirm sheet:** lists every selected item with its size, the total, and where it goes ("Trash. You can put it back."). Buttons: "Move to Trash" and "Cancel". Irreplaceable items (iOS backups) get their own line and a second tick box.
- **Move:** the existing `CleanupGate` and `NSFileManager.trashItemAtURL`. That is the same Trash Finder uses, and it needs no Finder Automation permission. One refused item no longer stops the others. Each result is reported per item.
- **Apps:** the app bundle first, then its ticked leftovers, as one undo group. If the app can't be moved (running, not owned by Fernando, or macOS App Management says no), nothing else in that group is touched and the app goes to "Fernando does this: quit it and drag it to the Trash in Finder."
- **iCloud:** `brctl evict <path>` per file, only when the file is uploaded, not uploading, current locally and has no conflicts. The check runs at scan time and again right before the call. Afterwards Jev confirms the file still exists as a cloud-only item. The undo is "Download again" (`brctl download <path>`). The iCloud module never imports the Trash function.
- **Results:** free space before, what moved (count and size), what was refused and why, what was made cloud-only, and free space after. The after line says how much is still sitting in the Trash. "Undo" restores a run. "Trash summary…" is D2.
- **Log:** the existing `~/Library/Application Support/Hey Jev/cleanup-audit.jsonl` gains `run_started` and `run_finished` records. "Past cleanups" on the results screen shows the last ten runs: date, items, sizes, where each went, before and after. The log stays on the Mac.

### What Jev never does here

No `rm`. No `sudo`. No password prompts. No `tmutil` deletes. No `launchctl`. No `npm`, `pip`, `brew` or `xcrun` commands. No changes to macOS privacy settings. If macOS asks for App Management or Full Disk Access, Fernando decides in System Settings himself, and without it the item moves to "Fernando does this".

### New installs and downloads

**None.** `mdls`, `brctl` and `osascript` ship with macOS. No new Python package is added.

---

## 4. Ordered PRs

| PR | Branch | One feature | Scan or act |
|---|---|---|---|
| 0 | `jev/cleanup-00-notes` | Reconcile the inventory with the REA notes. Record the protected paths locally. Docs only. | — |
| 1 | `jev/cleanup-01-safety` | Safety floor: `cleanup_rules.py`, the gate uses it, DerivedData split, `~/.cache` fixed. | Guard |
| 2 | `jev/cleanup-02-scan-caches` | Scan: caches, logs, Xcode, npm / pip / Homebrew, Trash size, plain reasons. | Scan |
| 3 | `jev/cleanup-03-scan-downloads` | Scan: large and old Downloads. | Scan |
| 4 | `jev/cleanup-04-review-screen` | The three-bucket review screen. | UI |
| 5 | `jev/cleanup-05-act-log` | Confirm sheet, per-item results, before and after, log, Empty Trash. | Act |
| 6 | `jev/cleanup-06-scan-apps` | Scan: unused apps with size and last used. | Scan |
| 7 | `jev/cleanup-07-scan-leftovers` | Scan: leftovers for installed apps and for apps that are gone. | Scan |
| 8 | `jev/cleanup-08-remove-apps` | Remove an app with its leftovers. | Act |
| 9 | `jev/cleanup-09-scan-icloud` | Scan: iCloud files that are uploaded and local. | Scan |
| 10 | `jev/cleanup-10-icloud-evict` | Make iCloud files cloud-only. | Act |
| 11 | `jev/cleanup-11-switch-over` | Point Mac health at Jev's cleanup, README, parity run against Eney. | Wrap-up |

Each PR starts from a fresh `main` after the previous one is merged.

---

## 5. PR details

### PR 0: Reconcile with the REA notes (docs only, on the Mac)

- **Do:** read the three notes. For every cleanup feature in them, find its row in section 1 or add one under row 18 with what Eney does (behavior only, in your own words), what Jev has, and which PR covers it. If a feature fits no PR, add it to a "Not covered yet" list at the end of section 1 and stop for Fernando.
- **Do:** create `~/Library/Application Support/Hey Jev/cleanup-protected.json` on the Mac with the real paths of VoiceStudio, the Luigi's Mansion, High On Life and DmIOS build folders, and iCloud Jarvis. Find them with `ls` and `mdfind -name` only. Don't open anything inside them. This file is never committed.
- **Do:** add `cleanup-protected.example.json` to the repo (placeholder paths) and the real file's name to `.gitignore` notes.
- **Do:** record in the PR body, not in the repo: where CleanMyMac lives (a Setapp path or not), whether Desktop & Documents sync to iCloud, and the macOS version.
- **Files:** `docs/plans/jev-cleanup.md`, `cleanup-protected.example.json`. No code.
- **Hand test:**
  - [ ] Every cleanup feature in the three notes has a row in section 1.
  - [ ] The local protected file exists, lists real folders, and `git status` doesn't show it.
  - [ ] No text, table or screenshot from Eney is in the diff.

### PR 1: Safety floor

- **Files:** new `commands/cleanup_rules.py` (pure, no AppKit); `commands/cleanup_gate.py` (`refusal` calls `cleanup_rules`); `commands/storage_scan.py`; new `tests/fake_home.py`, `tests/test_cleanup_rules.py`; `tests/test_storage_scan.py` updated.
- **Build:**
  - `protected_reason(path, home, extra=())` and `fernando_reason(path, home, uid, writable)` per the tables in section 2. `load_protected(path)` reads the local JSON and returns `()` when it is missing or broken.
  - `bucket_of(proposal)` returns `safe`, `your_call`, `apps`, `left_alone` or `fernando`.
  - `Proposal` gains optional fields with defaults so old callers work: `kind` (`file`, `app`, `leftover`, `icloud`, `trash`), `bucket`, `detail`, `group`.
  - `storage_scan.LOCATIONS`: Hugging Face becomes `leave_alone`, not deletable. CoreSimulator becomes report-only (D7). DerivedData becomes one row per project folder, and protected names become `leave_alone`.
  - The gate keeps every existing check (24 hours, symlinks, limits, home only) and adds `protected_reason` for the item and every descendant.
- **Acceptance:** with the fake home, no protected path can get an approval token. The card shows them greyed. All existing storage tests still pass.
- **Unit tests:** each rule row, positive and negative (for example `Library/Caches/com.example.jarvisnotes` is protected by the name rule, and that is intended); `.git` ancestor; `.download` bundle; database file names with nothing opened (monkeypatch `builtins.open` to fail); missing and malformed local JSON; `fernando_reason` for another uid and for a read-only parent; the gate refuses each protected path at `approve_click` and again at `execute`.
- **Hand test:**
  - [ ] Storage Scan: Hugging Face models show with a size and no live checkbox.
  - [ ] DerivedData shows one row per project. Any Luigi's Mansion, High On Life or DmIOS row is greyed as "Left alone".
  - [ ] CoreSimulator has no live checkbox.
  - [ ] Base checks B1–B5.

### PR 2: Scan caches, logs, Xcode and developer caches

- **Files:** `commands/storage_scan.py`, `commands/cleanup_rules.py` (reason table), tests.
- **Build:**
  - One walk per item returns size, newest change time, symlink seen, database name seen. Rows changed in the last 24 hours, partial rows, and rows with symlinks are not "safe" and say why.
  - Rows per child for `~/Library/Logs`, iOS / watchOS / tvOS DeviceSupport.
  - Named rows: npm (`~/.npm/_cacache`), pip (`~/Library/Caches/pip`), Homebrew (`~/Library/Caches/Homebrew`). Paths only. No package-manager command is run.
  - Trash: size and item count, bucket "your call", not selectable (PR 5 adds the button).
  - A plain reason on every row.
- **Unit tests:** fake home with each folder; reasons present for every category; a recently changed cache is not safe; `~/.cache/pip` is never listed as deletable; the scan leaves the tree byte-for-byte unchanged (compare a listing before and after); cancel and limit still work.
- **Hand test:**
  - [ ] npm, pip and Homebrew appear by name with sizes close to `du -sh` on each folder.
  - [ ] DeviceSupport shows one row per OS version.
  - [ ] The Trash row shows a size and can't be ticked.
  - [ ] Base checks.

### PR 3: Scan large and old Downloads

- **Files:** `commands/storage_scan.py` (calls into `commands/tidy_downloads.py`), tests.
- **Build:** top level of Downloads only, through the existing `scan_folder`, `build_report` and `find_duplicates`. Rows for old installers (90 days), large files (500 MB), possible duplicates (the copy, never the original), and files older than a year. All "your call". Active downloads are skipped and counted in "Left alone". Replace the old recursive installer walk for Downloads with this, and keep the iTunes software-update folders.
- **Unit tests:** fake Downloads with each case; a `.download` bundle and a `.crdownload` file never become rows; a duplicate row names the copy; one file that is both old and large appears once; the "tidy my downloads" reply is unchanged.
- **Hand test:**
  - [ ] Start a large download in Safari, scan while it runs: the partial file is not offered.
  - [ ] Old installers and large files match what "tidy my downloads" says.
  - [ ] Base checks.

### PR 4: Three-bucket review screen

- **Files:** new `commands/cleanup_view.py` (pure: sections, totals, row text, selection maths); `commands/storage_scan_ui.py` (AppKit only); new `scripts/make_cleanup_fake_home.py`; tests.
- **Build:** the screen in section 3. `JEV_CLEANUP_HOME` honoured only inside `~/Documents/.cos-tmp`. The existing "Move selected to Trash" button keeps working exactly as today until PR 5 replaces it. Refuse to open in Zoe mode.
- **Unit tests:** `sections(rows)` puts every fake-home row in the right bucket; totals; the default ticks (safe yes, the rest no); greyed rows are never counted in the selection; `JEV_CLEANUP_HOME` outside `.cos-tmp` is ignored; row text has a size and a reason for every row.
- **Hand test:**
  - [ ] Three headed sections with counts and totals, then "Left alone" collapsed.
  - [ ] Every row has a size and a one-line reason you understand without help.
  - [ ] Only "Safe to delete" rows start ticked.
  - [ ] Resize the window: nothing overlaps, long paths truncate in the middle.
  - [ ] Light and dark mode both read well. VoiceOver reads the row name, size and reason.
  - [ ] Base checks.

### PR 5: Act, before and after, and the log

- **Files:** `commands/cleanup_gate.py`, `commands/cleanup_view.py`, `commands/storage_scan_ui.py`, tests.
- **Build:** the confirm sheet; per-item results (a refused item is skipped and reported, the rest continue); free space read before the move and after it with the same key; `run_started` / `run_finished` log records; the results screen with Undo; "Past cleanups"; "Trash summary…" showing size and item count and offering to open Trash in Finder. Emptying stays manual.
- **Acceptance:** nothing moves on any single click. The token is still single-use. A crash between "requested" and "trashed" is visible in the log.
- **Unit tests:** a batch with one refused item moves the others; the token can't be replayed; results text (moved, refused with reasons, still in Trash); run records and the last-ten reader with a broken line in the file; the empty-Trash path is reachable only through its own confirm (source test); Undo restores a whole run and refuses to overwrite.
- **Hand test** (first with `JEV_CLEANUP_HOME`, then for real):
  - [ ] Make test junk: `mkdir -p ~/Library/Caches/jev-cleanup-test && dd if=/dev/zero of=~/Library/Caches/jev-cleanup-test/blob bs=1m count=50 && touch -t 202611010000 ~/Library/Caches/jev-cleanup-test/blob ~/Library/Caches/jev-cleanup-test`
  - [ ] It appears under "Safe to delete". Untick everything else.
  - [ ] "Review and move to Trash…" opens a sheet listing that one item and 50 MB. Cancel: nothing moved.
  - [ ] Again, then "Move to Trash": the folder is in the Trash, and Finder offers Put Back on it.
  - [ ] Results show free space before and after, and say 50 MB is still in the Trash.
  - [ ] Undo: the folder is back where it was.
  - [ ] Move it again, then "Trash summary…": the sheet shows the whole Trash's size. Cancel leaves the Trash alone. (Empty it only if you want to.)
  - [ ] "Past cleanups" lists these runs with the right sizes.
  - [ ] Base checks.

### PR 6: Scan unused apps

- **Files:** new `commands/cleanup_apps.py` (pure, with an injected metadata runner), `commands/storage_scan.py`, tests.
- **Build:** apps in `/Applications` and `~/Applications` (top level, plus one level of subfolders). Size from the same bounded walk. Last used from `mdls -name kMDItemLastUsedDate -raw <path>` as an argument list through the injected runner. "Never opened" when there is no date. An app is offered when it has not been used in `UNUSED_APP_DAYS` (D3). Never offered: anything running, Jev, Apple apps under `/System`, protected names, Xcode. Root-owned apps (Mac App Store installs) and everything under `/Applications/Setapp` go to "Fernando does this". Scan only: rows can't be ticked until PR 8.
- **Unit tests:** fake `Applications` with `Info.plist` files; `mdls` output parsing including `(null)`, a bad date and a timeout; the 90-day edge; running apps excluded (injected list); Xcode, VoiceStudio and Jev never offered; a root-owned app lands in "Fernando does this".
- **Hand test:**
  - [ ] "Remove apps" lists apps with a size and "Last opened <date>" or "Never opened".
  - [ ] Spot-check three apps against Finder → Get Info ("Last opened").
  - [ ] Xcode, VoiceStudio, Jev, Eney and Setapp are not offered for removal.
  - [ ] No row in this section can be ticked yet.
  - [ ] Base checks.

### PR 7: Scan app leftovers

- **Files:** new `commands/cleanup_leftovers.py` (pure), `commands/storage_scan.py`, tests.
- **Build:**
  - **For an installed app** (shown under its row in "Remove apps"): items whose name is exactly the bundle id, or the app's name for Application Support and Logs, in `~/Library/{Application Support, Caches, Containers, Preferences, Saved Application State, HTTPStorages, WebKit, Logs, LaunchAgents}`. Group Containers are listed only when the name ends with the bundle id, and start unticked because other apps from the same maker may share them.
  - **Orphans** (always "your call"): entries in `~/Library/{Application Support, Containers, Group Containers}` whose bundle id matches no installed app. "Installed" means every app in the PR 6 folders plus `/System/Applications`, `/Applications/Utilities` and `/Applications/Setapp`. Skipped: `com.apple.*`, anything protected, and any name Jev can't tie to a bundle id with confidence (those are counted in "Left alone" as "not sure whose this is").
  - A container whose folder name isn't a bundle id may have its small metadata `.plist` read with `plistlib` to get the id. A plist is not a database. No other file is opened.
  - Every leftover that contains a database file name says "contains a database (size only)".
- **Unit tests:** exact-match only (`com.foo.bar` doesn't claim `com.foo.barista`); Group Container suffix rule; orphans never include `com.apple.*`, protected names, or an app that is installed in `/Applications/Setapp`; `NoteStore.sqlite` group container is "Left alone"; database flag set without opening the file; uncertain names are not offered.
- **Hand test:**
  - [ ] Expand one app in "Remove apps": its leftovers are listed with sizes and they are really that app's.
  - [ ] "Your call" shows leftovers for apps you know you removed. Check three by name.
  - [ ] Nothing from Notes, VoiceStudio, Jev or any Apple app is offered.
  - [ ] Any row with a database says "size only".
  - [ ] Base checks.

### PR 8: Remove an app with its leftovers

- **Files:** `commands/cleanup_gate.py` (grouped moves), `commands/cleanup_apps.py`, `commands/cleanup_view.py`, `commands/storage_scan_ui.py`, tests.
- **Build:** the app flow in section 3. Before the sheet opens: the app must not be running (Jev says "Quit <app> first" and does not quit it for you), must be owned by Fernando, and must pass every rule. The sheet lists the app and each leftover with sizes. Order: app first, then leftovers. One undo group. Orphan leftovers from PR 7 become tickable through the normal PR 5 flow.
- **Unit tests:** app move fails → no leftover is touched and the group reports "Fernando does this"; a refused leftover doesn't stop the others; undo restores the app and every leftover; a running app can't get a token; a `LaunchAgents` plist is listed with the note "stops after you log out and back in"; no `launchctl`, `pkgutil` or `sudo` string in the source.
- **Hand test:**
  - [ ] Install a small free app you don't need, open it once, quit it. With `UNUSED_APP_DAYS` temporarily 0 through the test hook the PR documents, it appears under "Remove apps".
  - [ ] With the app open, removal is refused with "Quit it first".
  - [ ] Remove it: the sheet lists the app and its leftovers. After confirm, all are in the Trash.
  - [ ] Undo puts the app and leftovers back and the app still opens.
  - [ ] A Mac App Store app shows under "Fernando does this" and can't be ticked.
  - [ ] If macOS asks for App Management permission, Jev shows no password prompt of its own. Deny it: the app moves to "Fernando does this".
  - [ ] Base checks.

### PR 9: Scan iCloud files

- **Files:** new `commands/cleanup_icloud.py` (pure classifier plus a lazy Cocoa reader), `commands/storage_scan.py`, tests.
- **Build:** roots are `~/Library/Mobile Documents/com~apple~CloudDocs`, plus `~/Documents` and `~/Desktop` only when they are iCloud items. For each regular file, read URL resource values (is ubiquitous, is uploaded, is uploading, downloading status, has unresolved conflicts). No file content is read. `evictable(attrs, now)` is true when: uploaded, not uploading, the local copy is current, no conflicts, 50 MB or more, not changed or opened in 30 days (D4), and no rule protects it. Skipped: anything inside a folder tree that has `.git`, packages and bundles (`.app`, `.photoslibrary`, `.xcodeproj` and similar), hidden files, `~/Documents/.cos-tmp`, and iCloud Jarvis. Rows are grouped by folder, top 200 by size, bucket "your call", reason "Already in iCloud. Making it cloud-only keeps the file and frees the space." Files still uploading are listed greyed: "Still uploading. Try again later." Scan only.
- **Unit tests:** every combination of the five attributes through `evictable`; size and age edges; a `.git` tree and a Jarvis path are skipped; an already cloud-only file is not offered; the Cocoa reader is never imported in tests; the scan opens no file.
- **Hand test:**
  - [ ] "Your call" shows iCloud files with sizes, grouped by folder.
  - [ ] Pick three and check in Finder that each has no cloud-upload icon (it is fully uploaded).
  - [ ] Copy a new large file into iCloud Drive and scan at once: it shows as "Still uploading" or not at all.
  - [ ] Nothing under iCloud Jarvis or any git repo is listed.
  - [ ] Rows can't be acted on yet.
  - [ ] Base checks.

### PR 10: Make iCloud files cloud-only

- **Files:** `commands/cleanup_icloud.py`, `commands/cleanup_view.py`, `commands/storage_scan_ui.py`, tests.
- **Build:** selected iCloud rows go through their own confirm sheet ("Make 6 files cloud-only, 3.1 GB. The files stay in iCloud and in Finder."). For each file: re-read the attributes, and only if `evictable` is still true run `brctl evict <path>` (argument list, timeout, injected runner). Then confirm the path still exists and now reads as not downloaded. Log `evicted` with the size. Results show per-file outcomes and a "Download again" button (`brctl download <path>`). If `brctl evict` fails on this macOS, report the error and stop. Don't fall back to anything else without Fernando's say-so (the named alternative is Apple's `NSFileManager.evictUbiquitousItemAtURL`, same effect, no install).
- **Unit tests:** a file that started uploading again between scan and act is skipped; the runner gets exactly `["brctl", "evict", path]`; a non-zero exit is reported and the next file continues; a path that vanished after evict is logged as an error in red and stops the run; the module's source has no Trash, remove or unlink call.
- **Hand test:**
  - [ ] Put a 100 MB test file in iCloud Drive, wait until Finder shows it as uploaded, and backdate it: `touch -t 202609010000 <file>`.
  - [ ] It appears. Confirm: Finder now shows the cloud-download icon, and the file is still listed in Finder and on iCloud.com.
  - [ ] Free space after is higher than before by about the file's size.
  - [ ] "Download again" brings it back, and it opens.
  - [ ] Try a file that is mid-upload: Jev refuses it.
  - [ ] Base checks.

### PR 11: Switch over

- **Files:** `mini_bar.py` (Mac health chip, Quick Command title), `full_window.py` (sidebar "Mac" row), `assistant_ui.py` wiring, `README.md`, tests that pin the chip phrase.
- **Build:** the Mac health chip and the sidebar "Mac" row open Jev's cleanup screen (D5). The Quick Command is renamed "Clean Up Mac". "CleanMyMac Scan" stays as its own Quick Command. The `low_disk` reaction keeps highlighting the chip, which now opens Jev's screen (scan only until Fernando clicks). README gets a short "Mac cleanup" section. Add the parity table to the PR body: Eney's three bucket totals from a fresh Eney scan next to Jev's, same day, with any gap explained.
- **Unit tests:** chip and sidebar plans; Quick Command order tests updated; the chip action never moves anything by itself.
- **Hand test:**
  - [ ] The Mac health chip opens Jev's cleanup, not CleanMyMac.
  - [ ] Run Eney's scan and Jev's scan the same day. Jev's "safe" total is within about 10% of Eney's, or the PR explains each difference.
  - [ ] Every item Eney called safe is in Jev's "Safe to delete" or has a stated reason for being elsewhere.
  - [ ] Base checks.

---

## 6. Risks

| Risk | What the plan does |
|---|---|
| A protected folder has a name the patterns miss. | PR 0 writes the real paths to the local file, PR 1 reads it, and B5 is checked by hand on every PR. |
| A cache belongs to an app that is running. | The 24-hour rule refuses anything changed in the last day, at scan time and again at move time. |
| Leftover matching claims another app's data. | Exact bundle-id match only. Group Containers start unticked. Uncertain names are never offered. Everything goes to the Trash and has Undo. |
| An iCloud file isn't really uploaded. | The upload flags are read twice, and `brctl evict` itself refuses a file that isn't uploaded. The file is never deleted. |
| macOS blocks Jev from Containers or other apps. | Jev reports "needs permission" and lists the item under "Fernando does this". It never asks for a password. |
| `mdls` has no last-used date. | The row says "Never opened (or macOS has no record)" and stays unticked. |
| The Trash fills the disk instead of freeing it. | Results say how much is waiting in the Trash, and D2 gives a confirmed way to empty it. |

---

## 7. Codex prompts (paste one at a time, after the previous PR is merged)

Every prompt assumes the Mac checkout at `~/Developer/hey-jev`, freshly pulled from `main`, with the Python 3.9 venv at `.venv`.

### Prompt: PR 0, reconcile with the REA notes

```
You are Codex, doing PR 0 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). This PR is docs only. Write no code.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-00-notes

Read first: docs/plans/jev-cleanup.md (all of it), then the three study notes in "~/Documents/Fernando Ceja/Developer/AI-Projects/REA/Requests/" whose names start with "how-eney-cleans-the-mac", "eney-mac-cleanup-narrowed-to-two-areas" and "eney-full-capability-inventory". Read them only. Don't edit that folder.

Do:
1. For every Eney cleanup feature in the notes, find its row in section 1 of the plan, or add a row under row 18: what Eney does (behavior only, in your own words), what Jev has today (name the file), what is missing, and which PR covers it. Remove the "(to be filled in by PR 0)" row when done. If a feature fits no PR, list it under a new "Not covered yet" heading at the end of section 1.
2. On the Mac only, create "~/Library/Application Support/Hey Jev/cleanup-protected.json": {"paths": [...]} with the real folders for VoiceStudio, the Luigi's Mansion, High On Life and DmIOS build folders, and iCloud Jarvis. Find them with ls and mdfind -name only. Don't open or read anything inside them. Never commit this file or paste its contents into the PR.
3. Add cleanup-protected.example.json to the repo root with placeholder paths, like rea-blocklist.example.json.
4. In the PR body (not in the repo), state: whether CleanMyMac is installed under /Applications/Setapp, whether Desktop and Documents sync to iCloud, and the macOS version.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green (nothing should have changed). Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 0: reconcile inventory with REA notes". Body: what changed in the inventory, the "Not covered yet" list if any, and the PR 0 hand-test checklist from the plan as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 1.
```

### Prompt: PR 1, safety floor

```
You are Codex, building PR 1 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PR 0 is merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-01-safety

Read first: the plan (sections 2, 3 and "PR 1"), commands/cleanup_gate.py, commands/storage_scan.py, commands/storage_scan_ui.py, tests/test_storage_scan.py, tests/mac_guard.py, tests/conftest.py, cleanup-protected.example.json.

Build:
1. New commands/cleanup_rules.py. Pure Python 3.9, no AppKit, no subprocess, never opens a file except load_protected reading the one local JSON. Functions: protected_reason(path, home, extra=()) and fernando_reason(path, home, uid=None, writable=None) implementing every row of the two rule tables in section 2 of the plan; load_protected(path) returning a tuple of paths, () when the file is missing or malformed; bucket_of(proposal) returning "safe", "your_call", "apps", "left_alone" or "fernando". Name matching ignores case, spaces and punctuation. Database detection is by file name from os.scandir only.
2. commands/cleanup_gate.py: Proposal gains optional fields kind="file", bucket="", detail="", group="" (defaults keep old callers working). refusal() keeps every existing check and also calls protected_reason and fernando_reason for the item and each descendant. The local protected file is loaded once per gate.
3. commands/storage_scan.py: Hugging Face models become leave_alone and not deletable. CoreSimulator becomes report-only. Xcode DerivedData becomes one row per project folder; a project whose name is protected is leave_alone. Every row gets its bucket from bucket_of.
4. New tests/fake_home.py with build(tmp_path) as described under "Tests and the fake home" in the plan. New tests/test_cleanup_rules.py covering the PR 1 unit tests in the plan. Update tests/test_storage_scan.py; keep test_no_permanent_removal_code and extend it to cleanup_rules.py, adding "sqlite3" to the forbidden strings.

Out of scope: any UI change beyond what falls out of the new row values, any new scan area, any new action.

Acceptance: the PR 1 acceptance line in the plan.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 1: safety floor". Body: summary, files, tests run, and the plan's PR 1 hand test plus base checks B1–B5 as checkboxes for Fernando.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 2.
```

### Prompt: PR 2, scan caches, logs, Xcode and developer caches

```
You are Codex, building PR 2 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–1 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-02-scan-caches

Read first: the plan (sections 2, 3 "Scan" and "PR 2"), commands/storage_scan.py, commands/cleanup_rules.py, commands/cleanup_gate.py, tests/fake_home.py, tests/test_storage_scan.py.

Build:
1. commands/storage_scan.py: measure() does one walk and returns size, partial, newest change time, symlink_seen and database_seen. lstat and scandir only. Nothing is opened.
2. Rows changed in the last 24 hours, partial rows and rows with a symlink inside are never "safe"; each says why in plain words.
3. One row per child for ~/Library/Logs and for iOS, watchOS and tvOS DeviceSupport.
4. Named rows for npm (~/.npm/_cacache), pip (~/Library/Caches/pip) and Homebrew (~/Library/Caches/Homebrew). Use the paths only. Don't run npm, pip or brew.
5. Trash: size and item count, bucket "your_call", not deletable in this PR.
6. commands/cleanup_rules.py: a REASONS table with one plain sentence per category, in Jev's own words. Every row carries one.
7. Scan only. No new action, no UI change.

Tests: the PR 2 unit tests in the plan, all against tests/fake_home.py. Include the test that the scan leaves the tree unchanged, and one that builtins.open is never called during a scan.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 2: scan caches, logs, Xcode and developer caches". Body: summary, files, tests run, and the plan's PR 2 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 3.
```

### Prompt: PR 3, scan large and old Downloads

```
You are Codex, building PR 3 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–2 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-03-scan-downloads

Read first: the plan (section 2 and "PR 3"), commands/tidy_downloads.py, tests/test_tidy_downloads.py, commands/storage_scan.py, commands/cleanup_rules.py, tests/fake_home.py.

Build:
1. commands/storage_scan.py: for Downloads, reuse tidy_downloads.scan_folder, build_report and find_duplicates (top level only). Emit rows for old installers (OLD_DAYS), large files (LARGE_BYTES), possible duplicates (the copy, never the original) and files over a year old. Bucket "your_call". One row per file even when it matches more than one test; the reason names the strongest one.
2. Active downloads (.download, .crdownload, .part, .partial, or anything inside such a bundle) never become rows. Count them in "left_alone" with the reason "Still downloading".
3. Remove the old recursive installer walk for Downloads. Keep the iTunes software-update folders.
4. The spoken and typed "tidy my downloads" reply must not change.
5. Scan only.

Tests: the PR 3 unit tests in the plan, on tests/fake_home.py. All existing tidy tests still pass unchanged.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 3: scan large and old Downloads". Body: summary, files, tests run, and the plan's PR 3 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 4.
```

### Prompt: PR 4, three-bucket review screen

```
You are Codex, building PR 4 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–3 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-04-review-screen

Read first: the plan (section 2 "The four places a finding can land", section 3 "Review screen", and "PR 4"), commands/storage_scan_ui.py, commands/storage_scan.py, commands/cleanup_rules.py, full_window.py (PALETTE and layout helpers), how assistant_ui.py starts the storage card (kind "storage_scan") and lays it out, commands/tidy_downloads.py (human_size), commands/rea_study_ui.py (the Zoe mode check).

Build:
1. New commands/cleanup_view.py. Pure, no AppKit. sections(rows) -> ordered sections "Safe to delete", "Your call", "Remove apps", "Left alone", each with rows, count and total bytes; row_text(row) -> name, human size, plain reason, path; default_selected(row) (safe rows only); selection_total(rows, selected); scan_home(env, real_home) which returns JEV_CLEANUP_HOME only when it resolves inside ~/Documents/.cos-tmp, else real_home.
2. commands/storage_scan_ui.py: draw the screen from cleanup_view. Native AppKit, Jev's palette and type from full_window.PALETTE. Header with free space and "Scan again"; three headed sections with counts and totals; "Left alone" collapsed; each row has a checkbox, name, size, reason and a small middle-truncated path; greyed rows show why and can't be ticked; footer shows "Selected: N items, X". Original layout and wording — don't imitate Eney's screen.
3. Keep the existing "Move selected to Trash" behavior exactly as it is. PR 5 replaces it.
4. Refuse to open in Zoe mode, the same way rea_study_ui does. Accessibility labels on rows read name, size and reason.
5. New scripts/make_cleanup_fake_home.py: builds a fake home under ~/Documents/.cos-tmp/cleanup-fake-home using tests/fake_home.py's builder, and prints the path.

Tests: the PR 4 unit tests in the plan (pure functions only; no AppKit import in tests).

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body. Attach two screenshots (light and dark) saved under ~/Documents/.cos-tmp, taken with JEV_CLEANUP_HOME set to the fake home.

Open a DRAFT PR titled "Jev cleanup · PR 4: three-bucket review screen". Body: summary, files, tests run, and the plan's PR 4 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 5.
```

### Prompt: PR 5, act, before and after, and the log

```
You are Codex, building PR 5 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–4 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-05-act-log

Read first: the plan (section 3 "Act", decision D2, and "PR 5"), commands/cleanup_gate.py, commands/cleanup_view.py, commands/storage_scan_ui.py, commands/storage_scan.py (free_space), commands/system.py (empty_trash), tests/test_storage_scan.py.

Build:
1. Confirm sheet: the footer button becomes "Review and move to Trash…". It opens a sheet listing every selected item with its size, the total, and "Trash. You can put it back." Buttons: "Move to Trash", "Cancel". Irreplaceable items get their own line and a second tick box that must be ticked. Nothing moves before "Move to Trash" is clicked.
2. commands/cleanup_gate.py: approve_click no longer raises for the whole batch when one item is refused. It returns a token for the allowed items and the refusals with reasons. execute keeps its re-check before each move. Tokens stay single-use. Keep using the injected trash function (NSFileManager trashItemAtURL in the app).
3. Runs: log run_started (free space before, item count, bytes) and run_finished (free space after, moved bytes, refused count). Read free space with the same key both times. Add last_runs(n=10) that reads the JSONL and skips broken lines.
4. cleanup_view: results_text(run) -> free before, moved count and size, refused items with reasons, "X is still in the Trash", free after.
5. Results screen with "Undo" (restores the whole run; refuses to overwrite), "Past cleanups" (last ten runs), and "Trash summary…". That button shows the Trash summary and offers to open Trash in Finder. Emptying stays manual.
6. Trash row from PR 2 stays unticked; "Trash summary…" is its only action.

Tests: the PR 5 unit tests in the plan, with an injected trash function and a fake clock. Extend the no-permanent-removal source test to every cleanup module.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body. Run the hand test once yourself with JEV_CLEANUP_HOME set to the fake home and say so in the PR; leave the real-home hand test to Fernando.

Open a DRAFT PR titled "Jev cleanup · PR 5: confirm, move to Trash, before and after, log". Body: summary, files, tests run, and the plan's PR 5 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 6.
```

### Prompt: PR 6, scan unused apps

```
You are Codex, building PR 6 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–5 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-06-scan-apps

Read first: the plan (decision D3 and "PR 6"), commands/apps.py (_read_bundle_id, app_index, running_regular_apps), commands/shell.py (_run), commands/storage_scan.py, commands/cleanup_rules.py, commands/cleanup_view.py, tests/fake_home.py, tests/mac_guard.py.

Build:
1. New commands/cleanup_apps.py. Pure logic with injected runners. find_apps(roots) for /Applications and ~/Applications (top level plus one level of subfolders); bundle id through the existing _read_bundle_id (Info.plist only); size from storage_scan.measure; last_used(path, run) which calls ["mdls", "-name", "kMDItemLastUsedDate", "-raw", path] as an argument list with a timeout and parses the date, returning None for "(null)", a bad date, an error or a timeout; is_unused(last_used, now, days=UNUSED_APP_DAYS) with UNUSED_APP_DAYS = 90 and None counting as unused; a test hook to override the day count that the PR body documents.
2. Never offered: a running app (injected list of bundle ids), Jev itself, anything under /System, anything cleanup_rules protects (Xcode, VoiceStudio and the named projects). Root-owned apps and everything under /Applications/Setapp, plus Eney, go to "fernando" with a one-line how-to.
3. Rows: kind "app", bucket "apps", detail "Last opened <date>" or "Never opened (or macOS has no record)", plain reason. Not deletable in this PR: the checkbox is disabled with "Removal comes in a later update".
4. Scan only. No app is quit, opened or moved.

Tests: the PR 6 unit tests in the plan, with a fake Applications folder added to tests/fake_home.py and a fake mdls runner. No real subprocess.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 6: scan unused apps". Body: summary, files, tests run, and the plan's PR 6 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 7.
```

### Prompt: PR 7, scan app leftovers

```
You are Codex, building PR 7 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–6 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-07-scan-leftovers

Read first: the plan (section 2 rule tables and "PR 7"), commands/cleanup_apps.py, commands/cleanup_rules.py, commands/storage_scan.py, commands/cleanup_view.py, commands/storage_scan_ui.py, tests/fake_home.py.

Build:
1. New commands/cleanup_leftovers.py. Pure.
   - leftovers_for(app, home): items in ~/Library/{Application Support, Caches, Containers, Preferences, Saved Application State, HTTPStorages, WebKit, Logs, LaunchAgents} whose name is exactly the bundle id (plus .plist or .savedState where that folder uses it), or exactly the app's name for Application Support and Logs. Group Containers only when the name ends with the bundle id; those start unticked with the reason "May be shared with other apps from the same maker".
   - orphans(home, installed_bundle_ids): entries in ~/Library/{Application Support, Containers, Group Containers} tied to a bundle id that no installed app has. "Installed" covers the PR 6 folders plus /System/Applications, /Applications/Utilities and /Applications/Setapp. Skip com.apple.*, anything cleanup_rules protects, and any name that can't be tied to a bundle id with confidence (count those under "left_alone" as "Not sure whose this is").
   - A container whose folder name is not a bundle id may have its small metadata .plist read with plistlib to get the id. Open no other file.
2. Every leftover that contains a database file name carries "contains a database (size only)". Items holding NoteStore.sqlite or omnivoice.db are left_alone.
3. Rows: installed-app leftovers attach to the app's row (group = bundle id) and expand under it; orphans are kind "leftover", bucket "your_call". Not deletable in this PR.
4. Scan only.

Tests: the PR 7 unit tests in the plan, on tests/fake_home.py. Include a test that builtins.open is called only for .plist files.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 7: scan app leftovers". Body: summary, files, tests run, and the plan's PR 7 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 8.
```

### Prompt: PR 8, remove an app with its leftovers

```
You are Codex, building PR 8 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–7 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-08-remove-apps

Read first: the plan (section 3 "Act", "What Jev never does here", and "PR 8"), commands/cleanup_gate.py, commands/cleanup_apps.py, commands/cleanup_leftovers.py, commands/cleanup_view.py, commands/storage_scan_ui.py.

Build:
1. commands/cleanup_gate.py: grouped moves. A group is one app plus its ticked leftovers. Order: the app bundle first. If the app can't be moved (running, not owned by Fernando, refused by a rule, or macOS says no), touch nothing else in the group and report "Fernando does this: quit <app> and drag it to the Trash in Finder." If the app moves, move each leftover; a refused leftover is reported and the rest continue. The whole group is one undo.
2. A running app can't get an approval token. Jev says "Quit <app> first" and never quits it for the user.
3. Confirm sheet for apps: the app and every leftover with sizes and the total. Leftovers with a database say "contains a database (size only)". Group Containers start unticked. A LaunchAgents plist says "stops after you log out and back in".
4. Orphan leftovers from PR 7 become tickable and go through the normal PR 5 flow.
5. Never call launchctl, pkgutil, sudo, osascript or any uninstaller. Never show a password prompt. If macOS denies the move, report "needs permission" and list the item under "Fernando does this".

Tests: the PR 8 unit tests in the plan, with injected trash and running-app functions. Source test: no "launchctl", "pkgutil" or "sudo" in the cleanup modules.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body. Don't remove any real app yourself; the hand test is Fernando's.

Open a DRAFT PR titled "Jev cleanup · PR 8: remove an app with its leftovers". Body: summary, files, tests run, and the plan's PR 8 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 9.
```

### Prompt: PR 9, scan iCloud files

```
You are Codex, building PR 9 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–8 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-09-scan-icloud

Read first: the plan (decision D4, section 3 "Scan", and "PR 9"), commands/storage_scan.py (free_space shows the lazy Foundation import pattern), commands/cleanup_rules.py, commands/cleanup_view.py, tests/fake_home.py.

Build:
1. New commands/cleanup_icloud.py.
   - evictable(attrs, now, min_bytes=50 MiB, idle_days=30): pure. True only when is_ubiquitous, is_uploaded, not is_uploading, the local copy is current, no unresolved conflicts, size at or above min_bytes, and both last-change and last-open are older than idle_days.
   - status_reason(attrs): plain words for why a file is or isn't offered ("Still uploading. Try again later.", "Already cloud-only", and so on).
   - read_attrs(path): the only Cocoa code. Lazy import. Reads NSURL resource values (is ubiquitous, uploaded, uploading, downloading status, unresolved conflicts) and never the file's contents. Tests never import it.
   - candidates(roots, reader, rules, now, cap=200): bounded walk with lstat and scandir. Skip hidden names, packages and bundles (.app, .photoslibrary, .xcodeproj and similar), any tree with a .git folder, ~/Documents/.cos-tmp, and everything cleanup_rules protects (iCloud Jarvis included).
2. Roots: ~/Library/Mobile Documents/com~apple~CloudDocs, plus ~/Documents and ~/Desktop only when the reader says they are iCloud items.
3. Rows: kind "icloud", bucket "your_call", grouped by folder, with the reason "Already in iCloud. Making it cloud-only keeps the file and frees the space." Files still uploading are greyed. Not actionable in this PR.
4. Scan only. Nothing is opened, so nothing downloads.

Tests: the PR 9 unit tests in the plan, with a fake reader that returns dicts. Include a test that builtins.open is never called.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 9: scan iCloud files that can be cloud-only". Body: summary, files, tests run, and the plan's PR 9 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 10.
```

### Prompt: PR 10, make iCloud files cloud-only

```
You are Codex, building PR 10 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–9 are merged.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-10-icloud-evict

Read first: the plan (section 3 "Act" iCloud bullet and "PR 10"), commands/cleanup_icloud.py, commands/cleanup_gate.py (log format and run records), commands/cleanup_view.py, commands/storage_scan_ui.py, commands/shell.py (_run).

Build:
1. commands/cleanup_icloud.py: evict(paths, reader, run, log, now). For each path: re-read the attributes; skip with a reason unless evictable() is still true; run exactly ["brctl", "evict", path] as an argument list with a timeout; then confirm the path still exists (os.path.lexists) and the reader now reports it as not downloaded. Log "evicted" with the size, or "evict_failed" with the reason. A non-zero exit is reported and the next file continues. If a path no longer exists after the call, log an error, stop the run and show it in red.
2. redownload(paths, run): ["brctl", "download", path] for the "Download again" button.
3. UI: iCloud rows get their own confirm sheet: "Make N files cloud-only, X. The files stay in iCloud and in Finder." Buttons "Make cloud-only" and "Cancel". Results show each file's outcome, free space before and after (same key as PR 5), and "Download again". The run is added to "Past cleanups".
4. This module must not import or call the Trash function, and must contain no remove, unlink or rmtree call. If brctl evict fails on this macOS, report it and stop. Don't add a fallback.

Tests: the PR 10 unit tests in the plan, with a fake reader and a fake runner. Source test for the forbidden calls.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body. Don't evict any real file yourself; the hand test is Fernando's.

Open a DRAFT PR titled "Jev cleanup · PR 10: make iCloud files cloud-only". Body: summary, files, tests run, and the plan's PR 10 hand test plus base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Don't start PR 11.
```

### Prompt: PR 11, switch over

```
You are Codex, building PR 11 of docs/plans/jev-cleanup.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 0–10 are merged, and Fernando approved decision D5.

Setup: git checkout main && git pull && git checkout -b jev/cleanup-11-switch-over

Read first: the plan (decision D5, "PR 11" and section 9), mini_bar.py (POPOVER_CHIPS mac_health, quick_commands, quick_command_leaves), full_window.py (CATEGORIES "Mac"), assistant_ui.py (how kind "storage_scan" starts the screen, and how chips send phrases), orb_character.py (low_disk), README.md, tests/test_popover_chips.py, tests/test_full_window.py, tests/test_qc_order.py, tests/test_tutor.py, tests/test_storage_scan.py.

Build:
1. The Mac health chip and the sidebar "Mac" row open Jev's cleanup screen instead of sending "cleanmymac scan". Opening it only scans.
2. Rename the Quick Command "Storage Scan" to "Clean Up Mac". Keep its id and position. Keep "CleanMyMac Scan" as its own Quick Command, unchanged.
3. The low_disk reaction keeps highlighting the chip. Nothing is moved without the confirm sheets.
4. README.md: a short "Mac cleanup" section in the README's own style: what is scanned, the three buckets, what is never touched, that everything goes to the Trash with Undo, and where the log lives.
5. Update the tests that pin the chip phrase, the sidebar phrase and the Quick Command order.
6. Parity run, with Fernando at the Mac: he runs a fresh Eney scan; you run Jev's scan the same day. Put a table in the PR body with both sets of bucket totals and one line per difference. Record totals only. Don't copy Eney's wording, screenshots or item text into the repo.

Verify: mkdir -p ~/Documents/.cos-tmp && .venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/pytest-cleanup" must be green. Paste the last line in the PR body.

Open a DRAFT PR titled "Jev cleanup · PR 11: switch Mac health to Jev's cleanup". Body: summary, files, tests run, the parity table, the plan's PR 11 hand test plus base checks, and the section 9 "Ready to remove Eney" checklist, all as checkboxes for Fernando.

HARD RULES — follow all of them, no exceptions:
- Never open or read app databases (.db, .sqlite, NoteStore.sqlite, omnivoice.db). Report their size only.
- Never touch: ~/.cache (Jev's Hugging Face models), VoiceStudio, Xcode itself, the Luigi's Mansion / High On Life / DmIOS build folders, iCloud Jarvis, active .download files, or anything under ~/Developer git repos.
- Never type or prompt for passwords. Anything that's root-owned or needs admin is listed as "Fernando does this" and is never forced.
- No Gatekeeper bypass. No new installs or downloads unless the plan names each one with its size and license. (This plan names none.)
- Never copy Eney's code, assets, or text. Behavior only, in Jev's original style.
- No GitHub Actions. Don't add, edit or wait on any workflow. Every PR is verified with local `python -m pytest` on the Mac, and scan logic is tested headless against a fake home folder.
- Temp files go only in ~/Documents/.cos-tmp.
- Nothing is removed without an explicit confirm click on a visible Jev card. Use the Trash, never rm, os.remove, unlink or shutil.rmtree.
- iCloud items are only made cloud-only (brctl evict), only after the upload has finished, and the file is never deleted.
- Don't merge and don't push to main. One branch and one draft PR per plan PR. Fernando approves; his Chief of Staff merges.
- Nothing new on the iPhone bridge or in Zoe mode. No new listening sockets. No network calls.
- Don't uninstall, open, modify or script Eney or Setapp. Don't touch ~/Documents/AI-Projects/Jarvis.

Stop after opening the draft PR. Uninstalling Eney and Setapp is Fernando's step, not yours.
```

---

## 8. Hand-test index

Each PR's checklist is in its section 5 entry and is copied into that PR's body by the prompt. Base checks B1–B5 (section 2) apply to all of them.

| PR | Needs a real move? | Safe way to test |
|---|---|---|
| 0, 1, 2, 3, 4, 6, 7, 9 | No. Scan and display only. | Open the screen and read it. |
| 5 | Yes | The `jev-cleanup-test` cache folder made in the checklist, first under `JEV_CLEANUP_HOME`. |
| 8 | Yes | A small free app installed just for the test. |
| 10 | Yes | A 100 MB test file in iCloud Drive. |
| 11 | No | Same-day scans in Eney and Jev. |

---

## 9. Ready to remove Eney (Fernando's checklist)

Jev never uninstalls Eney or Setapp. These are Fernando's steps, in order, and nothing here should be done until every box above it is ticked.

**Jev covers the cleanup**
- [ ] PRs 0–11 are merged and Jev is rebuilt from `main`.
- [ ] Section 1 has no "Not covered yet" items, or each one is knowingly dropped.
- [ ] The PR 11 parity run matched, or every difference is explained and accepted.
- [ ] One full real cleanup done in Jev: scan, tick, confirm, moved to Trash, before and after shown, run listed in "Past cleanups".
- [ ] Undo was tried once on a real run and restored everything.
- [ ] One real app was removed with its leftovers through Jev.
- [ ] One real iCloud file was made cloud-only and downloaded again.
- [ ] `~/.cache`, VoiceStudio, Xcode, the Luigi's Mansion / High On Life / DmIOS builds, iCloud Jarvis and `~/Developer` all still exist and still work after those runs.

**Nothing else still depends on Eney or Setapp**
- [ ] The "eney-full-capability-inventory" note was read once more for non-cleanup features. Each is in Jev already (the bubble v2 work covered the orb, capture, mark up, @ picker, translate chip, start my day and tidy) or knowingly dropped.
- [ ] Every app under `/Applications/Setapp` was looked at. Any you still use has a replacement or its own licence. This includes CleanMyMac if it is a Setapp copy; if it is, the "CleanMyMac Scan" Quick Command will say the app isn't installed, which is expected.
- [ ] The Mac health chip opens Jev's cleanup (PR 11).

**Review with me before doing these (money and accounts)**
- [ ] Setapp subscription: check the renewal date and cancel it in your Setapp account yourself. Source: your Setapp account page. Why it matters: uninstalling the app doesn't stop the billing.
- [ ] Sign out of Eney and Setapp before removing them.

**Remove (Fernando does this)**
- [ ] Quit Eney. Uninstall it and Setapp with Setapp's own uninstall option, following Setapp's current support instructions. Jev doesn't script this and doesn't type the password macOS asks for.
- [ ] Restart the Mac.

**After**
- [ ] Jev launches to Ready, and local pytest is green.
- [ ] Run Jev's scan. Any Eney or Setapp leftovers in `~/Library` appear under "Your call" as leftovers from apps that are gone. Review them, and move them to the Trash only if you want to.
- [ ] Root-owned leftovers (for example anything under `/Library`) appear under "Fernando does this". Remove them yourself or leave them.
- [ ] A follow-up PR, if you want one, removes `/Applications/Setapp` and `/Applications/Eney.app` from the gate's protected list and the Setapp paths from `commands/cleanmymac.py`. It isn't needed for anything to work.
