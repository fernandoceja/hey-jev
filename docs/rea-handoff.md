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
