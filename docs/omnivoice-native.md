# Native OmniVoice (personal Jev use only)

This is a clean-room implementation of FINAL SCOPE items 1–4 from the
November 8, 2026 behavior brief and Muse parity checklist. No VoiceStudio
source, assets, voice packs, or router structure were used. Jev's existing
`commands/voicestudio_voice.py` supplies the legacy request contract.

## License restrictions

**Personal use only. Never use this provider or its output for 80s Obsession,
paid work, commercial services, or commercial model training.** The
[OmniVoice model card](https://huggingface.co/k2-fsa/OmniVoice#license) states
that code is Apache-2.0 but pretrained weights are CC-BY-NC because of training
data restrictions. Apache licensing does not grant commercial model rights.
The card does not identify a CC license version; do not infer one. Retain
upstream attribution and verify the exact cached revision's terms before a live
run or redistribution; stop on a license/document mismatch.

The audio tokenizer has the separate
[Boson Higgs Audio 2 Community License](https://huggingface.co/bosonai/higgs-audio-v2-tokenizer/blob/main/LICENSE),
which incorporates the Meta Llama 3 license and acceptable-use policy. Its
redistribution terms require the agreements, notices, naming requirements for
applicable derivatives, and prominent attribution. It also restricts use to
improve other language models and requires an expanded license above its
100,000 annual-active-user threshold. These terms do not override the weights'
noncommercial restriction. This repository does not redistribute the materials.

Built with Higgs Materials licensed from Boson AI USA, Inc.

The upstream required full prominent notice is:

> Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc., All Right Reserved

The license additionally prints “based on Meta Llama 3” after that notice.
Preserve that wording and the complete agreements when distributing materials;
this documentation is not a replacement for them. Required distributed-copy
NOTICE text includes:

> Meta Llama 3 is licensed under the Meta Llama 3 Community License, Copyright © Meta Platforms, Inc. All Rights Reserved.
>
> Boson Higgs Audio 2 is licensed under the Boson Community License, Copyright © Boson AI USA, Inc. All Rights Reserved.

Only clone your own voice or one whose owner explicitly consented. References
and profile settings stay local; they are not sent to Fish or VoiceStudio.

## Runtime and provider

Set `JEV_TTS_PROVIDER=OMNIVOICE` in the normal Jev launch environment, then
restart. Fish remains the default. Native failures disable worker retries for
the session and fall through to VoiceStudio and then Fish. VoiceStudio's
one-second connect timeout and session skip remain intact. Existing explicit
read-aloud offers and Speaking→Ready `finally` cleanup are retained; none of
the new commands plays audio. No new bridge commands or listeners were added.

Set `JEV_OMNIVOICE_PYTHON` to the existing VoiceStudio runtime interpreter.
Without it, Jev checks `~/Library/Application Support/VoiceStudio/.venv/bin/python`
and `~/Library/Application Support/OmniVoice/.venv/bin/python`, in that order.
These are candidate locations, not verified installation paths. It fails clearly
if neither exists. No dependency was added to Jev. A Jev-owned runtime is a
separate approval-gated step **before any VoiceStudio uninstall**. Runtime/package,
Python version, device support and cached dependency compatibility remain Mac checks;
Jev's 3.9/3.12 test matrix is unchanged.

The child uses bounded JSON lines on stdin/stdout, never a network service.
Heavy imports and model loading happen only on first synthesis. Parent waits,
responses and request sizes are bounded. `JEV_OMNIVOICE_TIMEOUT` defaults to 180
seconds (maximum 1800); `JEV_OMNIVOICE_IDLE` defaults to 120 seconds (maximum
3600). Idle expiration exits the worker to release all model memory. A failed,
cancelled, malformed or timed-out request kills it and disables retries; explicit
reset or a Jev restart is needed. Native speech WAVs have their own cache.

The worker forces `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and local-only
snapshot/model resolution from `~/.cache/huggingface/hub/k2-fsa`'s standard
repository layout (`models--k2-fsa--OmniVoice`). It never installs or downloads.
Preserve that cache and the faster-whisper cache. The offline loader must reject
missing shards or tokenizer files; manually verify completeness and license terms
before live testing, without starting a download.

## Explicit commands

Run with Jev's Python; only the subprocess needs the isolated heavy runtime:

```sh
python -m scripts.omnivoice design --description "Warm, gentle storybook narrator" --text "Once upon a time." --output /absolute/path/story.wav
python -m scripts.omnivoice clone --name Fernando --reference /absolute/path/consented.wav --ref-text "Words spoken in the reference" --consent
python -m scripts.omnivoice import --name Existing --filename 379971dc.wav --consent
python -m scripts.omnivoice render --name Fernando --text "Hello, Jev." --output /absolute/path/reply.wav
```

Profiles live under `~/Library/Application Support/hey-jev/omnivoice`, containing
name, UTC creation time, copied reference WAV path, settings and consent. Creation
requires `--consent`; it is the user's assertion of authorization, never inferred
from a file's existence. Import reads only the explicitly named WAV directly under
`~/Library/Application Support/OmniVoice/voices`. It copies rather than moves;
it never reads or changes `omnivoice.db` or enumerates personal audio. Profile
names cannot traverse directories. Existing names are not overwritten. Preserve
both the original `voices/379971dc.wav` and `outputs/mic_8ea9fb5a.wav` independently.

Settings support `ref_text`, `seed`, `speed`, and a `pronunciation` dictionary
mapping whole words to spoken replacements. Pronunciation is applied locally
before synthesis and never passed as arbitrary engine kwargs. Settings may be
supplied through `Profiles.create`; there is no additional UI. Commands require
an explicit `.wav` destination, validate nonempty WAVs and replace the destination
only after success. Choose a new destination to preserve an earlier render.

## Engine adapter assumptions (unverified)

Only `commands/omnivoice_engine.py` imports engine dependencies. It assumes
`OmniVoice.from_pretrained(local_snapshot, local_files_only=True)` works with the
installed runtime and default device; `generate(text=...)` returns a list of mono
arrays at 24 kHz, as in the public model-card example. Reference conditioning uses
`ref_audio` and `ref_text`. Design conditioning assumes `instruct`; seed/speed
kwargs and device selection require verification. An unsupported API fails rather
than silently changing engines. No conditioning is assumed to produce the default
voice; matching VoiceStudio's sound requires listening on the Mac, not a mock claim.
Design produces a voice-conditioned line directly; persistence/reproducibility of
a designed voice is not asserted. Fix API assumptions only in this adapter during
the real test, with matching mocked tests.

## Real Mac acceptance procedure (pending)

1. Verify cached weights/tokenizer completeness, licenses, runtime interpreter and
   actual package versions without downloading. Record Mac model, OS, memory,
   runtime Python, torch/omnivoice versions, device and cached snapshot revision.
2. With no other voice render active, run:
   `python -m scripts.omnivoice_live_test --output /absolute/path/new-test-folder`.
   It writes WAVs and `report.json`, never plays them, and never falls back. A
   missing runtime/model or render failure is recorded as failure, not success.
3. Review cold first-render latency (process launch plus load plus synthesis), warm
   short reply, long reply, output durations and input text. RSS is the worker's
   resident memory sampled with `ps` every 50 ms; this can miss short peaks and
   excludes Jev/system/unified GPU allocation. Report those limits with the actual
   measured bytes. Do not call the 2.4 GB download size measured RAM. Idle testing
   verifies the old process exits, releasing its resident memory; it records RSS
   before idle. Crash testing kills a real worker, verifies failure/session disable,
   then explicitly resets and renders again. Report missing measurements as pending.
4. Compare prompts and latency honestly against Nov 1: cold 15.01s; warm time
   6.281s, date 7.349s, weather 13.123s, brief 32.618s. These are reference values,
   not pass thresholds; the script's prompts differ and are recorded in the report.
5. Through Jev with OMNIVOICE selected, request a text response, explicitly choose
   read aloud, and confirm native provider output with no fallback. Verify success,
   worker failure and cancellation leave Speaking→Ready and Jev usable. Retain this
   evidence alongside the script's report. Explicitly audition the default voice,
   a consented clone, and a Voice Design line against the existing ElevenLabs Zoe
   storybook MP3s; do not import/copy those assets into the implementation.
6. The report deliberately stays `gate: PENDING` for the manual listening/UI checks.
   CoS records final acceptance only after actual native audio and all required
   measurements/checks pass. Fish audio and mocked tests never satisfy this gate.

Implemented parity: subprocess TTS/default voice path, minimal Design, consented
profiles/clone and explicit read-only import, live measurement tooling. Real default
voice parity, API/device compatibility, measured performance and Mac UI acceptance
remain pending. Streaming read-aloud is a separate spec. Dubbing, transcription,
dictation, isolation, diarization, batch/longform, gallery, watermark, other engines
and MCP/API servers are out of scope per Muse's final disposition.

## Rollback and preservation

Set `JEV_TTS_PROVIDER=FISH` (or `VOICESTUDIO`) and restart Jev. Leave native
profiles and WAVs in place. The current VoiceStudio provider, Fish fallback,
VoiceStudio app/runtime, shared cache, original voice profiles and generated audio
are preserved. Do not uninstall VoiceStudio until the real Mac live gate passes,
Fernando explicitly approves, and a Jev-owned runtime is ready. No merge, push,
install, download or uninstall is part of this implementation task.

## Local validation evidence (November 8, 2026)

Full offline suites, with no dependency installs or model loads:

| Command | Runtime | Result |
| --- | --- | --- |
| `/tmp/jevtest-3.9/bin/python -m pytest -q` | Python 3.9.25 | 2099 passed, 1 skipped |
| `/tmp/jevtest-3.12/bin/python -m pytest -q` | Python 3.12.16 | 2099 passed, 1 skipped; 18 subtests passed |

`TMPDIR` was set to a generated scratch directory inside the repository to keep
writes local; that directory was removed afterward. Run suites sequentially:
a concurrent run exposed one suite's transient home-address fixture to another
suite's repository-wide guard. The sequential 3.9 rerun passed. New mocked tests
cover lifecycle, idle exit, crash/timeout/cancellation, bounded protocol, offline
loader flags, provider fallback, session skip, Speaking→Ready, profiles/consent,
pronunciation, WAV saving, Design CLI, no listener/playback calls, and live-report
success/failure bookkeeping. No real Mac audio, measured RAM or acceptance pass is
claimed by this evidence.
