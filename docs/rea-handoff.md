# REA clean-room handoff, schema 1.0

REA is the researcher, never an app or IPA builder. This portable format lets
REA later become its own app without changing builders. Research, Review and
Replicate Plan normalize their outputs into a request-local `spec/` directory.
Builders receive **only spec/**. They never receive the original target path,
request.md, logs, evidence binaries, proprietary code or assets.

```json
{
  "schema_version": "1.0",
  "request_id": "2026-11-06-1200-window-search",
  "created": "2026-11-06T12:00:00-08:00",
  "mode": "research",
  "target_kind": "app",
  "feature": "Window search",
  "suggested_builder": "none",
  "clean_room": true,
  "files": {
    "findings": "findings.md",
    "build_plan": "build-plan.md",
    "review": null
  }
}
```

All fields are required; unknown fields are rejected. All scalar fields except
clean_room are nonempty strings. `created` is ISO 8601. `mode` is research,
review, or replicate. `target_kind` is app, file, folder, repo, build, or unknown:
a coarse category, **never a path**. `suggested_builder` is nxnative, new_app, or
none. `clean_room` must be the boolean true. The files object has exactly the
keys above; review is `review.md` in Review mode and null otherwise. Listed
files must exist and cannot be symlinks. Findings and build plan are mandatory.

The runner copies root findings.md and build-plan.md (plus review.md for Review)
to spec/ and writes handoff.json after exit 0. Missing required artifacts fail
the run. Review reuses an existing request; the previous review is retained as
review.previous.md outside spec/. Absolute evidence paths are stripped from
builder-bound markdown, and path-bearing metadata is rejected. No original
target path key is allowed. Delivery copies only manifest-listed markdown and
the validated manifest, never arbitrary files or symlinks in spec/.

NXNative delivery requires explicit selection of an existing Inbox game and
rejects Mac app studies or suggested_builder=new_app. It copies to
Inbox/<Game>/rea-spec/ and never starts a build. Use Start NXNative Build next.
New App initializes a local repo with docs/spec/ and scaffolds from that alone.
No REA MCP tools are exposed to that builder. Neither builder installs software,
downloads packages, pushes, creates remotes, or receives the research target.

Research uses lawful interoperability only: no proprietary extraction, target
modification, licensing/DRM/signing bypass, Ryujinx/games/keys access, installs or
model downloads. Research writes only inside its request; scaffolding writes
only inside its new repo. Scoped builtin permissions do not sandbox the trusted
REA MCP server. All actions require an explicit Mac click outside Zoe mode and
are unavailable through the iPhone bridge.

## Four local workflows

1. Say or type `study how Safari does tabs`, `research tabs in Safari`, or
   `replicate tabs from Safari`. Jev opens Research or Replicate Plan with the
   feature and a fuzzy match from `/Applications` or `~/Applications`. An unknown
   app leaves the target unselected. **Start** must be clicked; acknowledgement
   is text only. No study or audio starts from the utterance.
2. **REA / Add to Wishlist** → enter feature, source app name/path, and optional
   notes in one form → **Save**. `add tabs from Safari to the REA wishlist`
   prefills that form; unknown source names are preserved for later resolution.
   **REA / Wishlist** → select item → **Replicate Plan** starts that item's plan
   directly when its source resolves to an existing target. This button authorizes
   the start; no second Start form appears. Missing targets instead open target/
   feature selection → **Start**. Starting links the request folder and marks the
   item planned. **Mark Built** updates status; **Remove** → **Confirm** removes
   only the list entry, never request files.
3. **REA / Review** → **Review against earlier study/spec** → choose prior REA
   request with spec or findings/build plan → choose your own target and feature
   → **Start** compares against that earlier study and writes into its request
   folder (retaining the previous review).
   Alternatively, **REA / Review** → **Review last change** → Jev, NXNative,
   Zoe Princess Academy (only when discovered), or Other → **Choose** → **Start**.
   Jev and NXNative resolve under `~/Developer/hey-jev` and `~/Developer/nxnative`.
   Zoe discovery checks local git origins under `~/Developer` for Fernando's
   Princess Academy repository. Python collects `git diff HEAD~1 --stat`,
   `git diff HEAD~1`, and `git log -5 --oneline` into request.md; new/shallow
   repositories get an explicit unavailable message. Last-change review writes
   into a new request folder. Both choices keep the target read only.
4. **REA / Send to Builder** → request → **Existing Repo** → preset/Other → new
   slug → **Continue**. Only an actual repository root with a clean worktree and
   a strict Fernando GitHub origin is accepted. It creates a separate worktree
   at `~/Developer/.rea-worktrees/<repo>-<slug>` on `rea/<slug>`, from origin's
   resolved default branch. Existing folders, registered worktrees, local and
   fetched remote branches are refused. Only validated spec files are copied
   into `docs/rea-spec/<slug>/`. Original target paths, request.md, evidence and
   research logs are never supplied to the builder.

The wishlist is
`~/Documents/Fernando Ceja/Developer/AI-Projects/REA/wishlist.json`, a JSON list
with exactly `id`, `feature`, `source_app`, `notes`, `added`, `status`, and
`request_folder`. Status is idea/planned/built. Linked requests must be direct
children of REA Requests. Updates use an exclusive sibling file, fsync and
atomic replace. Invalid JSON/schema is backed up to a unique `.corrupt-*`
sibling and the operation fails without overwriting the original. Symlinks and
unsafe request paths are refused. A user must repair the original before retrying.

## Existing Repo command contract

All commands below use subprocess argument lists (no shell). `R` is the chosen
repo, `W` the new worktree, `D` origin's default branch and `S` a validated slug
of at most 60 lowercase letters, numbers or hyphens, starting with a letter or
number. Origin must be exactly HTTPS or git@github.com SSH for
`fernandoceja/<repo>` with optional `.git`; push URLs must match the fetch URL.

```text
git -C R rev-parse --show-toplevel
git -C R remote get-url origin
git -C R remote get-url --push --all origin
git -C R status --porcelain
git -C R fetch origin
git -C R remote set-head origin --auto
git -C R symbolic-ref refs/remotes/origin/HEAD
git -C R check-ref-format --branch D
git -C R branch --list rea/S
git -C R branch -r --list origin/rea/S
git -C R worktree list --porcelain
git -C R worktree add -b rea/S W origin/D
```

Claude is invoked with cwd=W, Node 22+ prepended to PATH, and this exact argv
shape (`PROMPT` is the clean-room instruction in commands/rea_existing.py;
`//absolute/W/**` is generated from the canonical absolute worktree path):

```text
[claude, '-p', PROMPT,
 '--permission-mode', 'default',
 '--tools', 'Read,Glob,Grep,Write,Edit',
 '--allowedTools', 'Read', 'Glob', 'Grep',
 'Write(//absolute/W/**)', 'Edit(//absolute/W/**)',
 '--disallowedTools', 'Bash', 'mcp__rea__*',
 '--setting-sources', '', '--strict-mcp-config',
 '--mcp-config', '{"mcpServers":{}}']
```

Empty setting sources prevent inherited generic Write/Edit grants from bypassing
scope. Strict empty MCP configuration prevents exposing REA to the builder.
Missing required CLI flags fail closed before worktree creation. Claude has no
shell tools. After successful, uncancelled exit, Jev validates the live root,
branch and origin, then runs `git -C W add --all` and
`git -C W commit -m 'Implement REA S'` only if there are changes. No push occurs.
Cancellation terminates the process group and retains the worktree for inspection.
Failures retain files and logs; nothing is force-cleaned.

Completion offers **Open Folder**, **Show Diff**, **Push & Open PR**, and
**Discard Worktree**. Open Folder and Show Diff return to the action chooser.
Push is a separate explicit click: Jev revalidates origin/root/branch, fetches
and resolves the live default, requires a clean worktree, hard-refuses main,
master or the default, and runs only:

```text
git -C W push -u origin rea/S
```

Then it opens
`https://github.com/fernandoceja/<repo>/compare/<D>...rea%2F<S>?expand=1`
with each branch URL encoded. Fernando submits the PR himself; Jev never creates
one. Discard requires confirmation, live validation, a fetch, and a clean,
unpushed branch; it runs `git -C R worktree remove W` without force, followed by
`git -C R update-ref -d refs/heads/rea/S EXPECTED_HEAD`. The expected object ID
makes branch deletion conditional on its tip remaining unchanged. Pushed,
dirty or changed worktrees are retained, including cancelled work with edits.

Setup: use this Mac outside Zoe mode, existing Git/Node 22+/Claude Code CLI,
configured REA MCP for research, Git author identity, and existing GitHub access.
No setup command installs software or downloads models. All workflows refuse
Zoe mode and the iPhone bridge. No autoplay audio is added.

Offline validation (no installs):

```sh
mkdir -p ~/Documents/.cos-tmp
.venv/bin/python -m pytest -q --basetemp="$HOME/Documents/.cos-tmp/rea-tests"
.venv/bin/python -m compileall -q commands assistant_ui.py siri.py tests/test_rea_workflows.py
git diff --check
gh run list --repo fernandoceja/hey-jev --branch feat/rea-workflows
```

## Phase 2 backend adapter (Transport A)

The existing clicked local `claude -p` flow remains the default. The optional
paid `abliterated` lane is exposed through `commands.rea_adapter.Adapter`; lane
selector and import/export dialogs are deferred. No bridge access is added.
The adapter never invokes `claude-abliterated`: a human/coordinator manually
carries the exported directory to the paid box and carries results back.
It opens no connection and starts no process, build, playback, or retry.

API integration sequence (call only from an explicit Mac click outside Zoe mode):

1. `route(lane='local', unrestricted_need='')` resolves the lane. Requesting
   abliterated without a nonempty reason refuses that lane and returns local.
2. Stage only deliberately selected sanitized text under a source directory.
   Call `Adapter(data_dir=...).preview(source, relative_filenames, mode=...,
   feature=..., target_kind=..., lane=..., unrestricted_need=...,
   estimated_cost_usd=...)`. Show the entire preview as text, including routing
   refusal, reason, cost, cap status, names, byte sizes and content hashes.
   `approval_hash(preview)` hashes canonical sorted compact UTF-8 JSON.
3. Only the approval button handler calls `approve_click(preview, clicked=True)`.
   Pass that single-use opaque token and unchanged preview to
   `export(source, new_package_directory, request_id, preview, token)`.
   Tokens are in-memory, scoped to that exact preview, and consumed even on
   failure. Changed content or cap reservations require a new preview/click.
   A token cannot authenticate physical input itself: the caller must enforce
   the existing Mac click/Zoe guards; do not expose this API through the bridge.
4. Hand the package's `job.json` and `payload/` to the coordinator. Target text,
   including apparent instructions, is untrusted evidence only. The package
   includes that instruction explicitly. Do not execute anything from it.
5. Return `adapter-result.json` plus root `findings.md`, `build-plan.md`,
   `review.md` only for review mode, and `spec/handoff.json`. Call
   `import_result(returned_directory, new_request_directory, job_id)`.
   The request directory basename must equal the exported request ID.
   Import validates everything before creating a new request; it never overwrites
   an existing study. It copies validated markdown into spec for builders.
   `cancel(job_id)` permanently refuses subsequent import.

The returned envelope has exactly `schema_version: "adapter-1.0"`, `request_id`,
`job_id`, `lane: "abliterated"`, `status` (complete or failed), `usage`,
`estimated_cost_usd`, `basis` (actual tokens or estimated tokens), `errors`
(a list of strings), and `artifacts` (relative filename to SHA-256 hex digest).
Complete results require all mode-specific artifacts; failed results require an
empty artifacts object. Usage accepts nonnegative integer `input_tokens`,
`output_tokens`, `cache_read_tokens`, and `cache_write_tokens` only.
Imported errors are replaced by generic text. The stored envelope adds
`cap_overrun`, a conservative charge, and an explicit cache-write estimate label.
It remains at `<request>/adapter-result.json`, outside spec, and builders never
receive it. The handoff remains exactly schema 1.0 with no adapter fields.
Artifact hashes cover the original validated returned artifacts; the validated
handoff is preserved byte for byte.

Screening refuses absolute/home paths, sensitive filenames, symlinks (including
ancestor directories), app bundles, non-allowlisted text formats, invalid UTF-8,
control bytes, and sensitive keywords. `keywords=` adds configurable terms to
the default immigration/financial/family/personal blocklist. Files are limited
to 1 MiB each and 4 MiB total. Only selected files are exported; no target app,
repository tree, or local request/log is implicitly included. This conservative
screen may require manually rewriting benign material before approval.

The injectable app data directory defaults to
`~/Library/Application Support/Hey Jev/rea-adapter`. Its locked, fsynced JSONL
ledger records job/request mappings and reserves estimates before exposing a
package. Paid exports enforce $0.50/study and $1.00 per America/Los_Angeles day.
Reservations are replaced by the greater of reserved estimate, returned estimate,
and token-derived cost on import; overruns are flagged and count against the
original export day. Rates are input $1/M, output $2/M, cache read $0.10/M;
cache write uses an explicitly labeled estimate at input rate. These are local
accounting limits, not provider-enforced spend caps. Honest estimates and usage
are needed; manual box execution can exceed a reservation. Cancellation retains
its reservation because a carried job may already have run. Export failures after
reservation also retain it for human reconciliation. No automatic refunds,
retries, or duplicate exports for a request ID are allowed. Malformed ledger data
fails the operation; repair it manually rather than deleting spend history.
