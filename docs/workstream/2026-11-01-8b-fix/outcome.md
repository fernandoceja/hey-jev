# 8B proactive fix — November 1, 2026

Vehicle: existing PR #97, jev/eney-v2-08b-translate-chip. Main's revert stays until this branch passes the gate. Two distinct fix attempts; no third needed.

## Attempt 1 — f50d17b

Specific hypothesis, confirmed by executing the actual UI callback: `_translate_tick` references `commands` without importing it. It raises NameError at clipboard_is_paused before reading clipboard observations. `_translate_clicked` has the same omission. Other UI methods import commands locally, so there was no module-global binding.

Fix: local imports in both methods. Regression executes the actual callback AST without AppKit or a global commands binding, observes a stored Spanish snapshot, verifies visible state and dispatch through submission.

Focused suite: 136 passed. Full suite: 1888 passed, 1 skipped. CI Python 3.9/3.12 passed (push and PR runs). Live: Translate appeared; retained at 13.306 s and expired by 27.473 s. Click FAILED: TypeSafe selected timer_set for the explicit translation request and Jev replied “How long for? Want me to read it out loud?” Runtime log confirmed timer_action=set and action=timer_set. Screenshots in attempt-1.

## Attempt 2 — 7355ff6

Specific hypothesis: the explicit translation payload fell through to TypeSafe, whose action classifier interpreted copied sentence content as a Mac command. Confirmed by attempt 1 runtime log, including the exact heard translation prefix followed by timer_set.

Fix: decide recognizes the exact `translate this to English:` prefix with a nonempty payload and chooses the existing llm answer path. _handle_turn consumes that early answer decision without calling TypeSafe. This remains a normal typed turn: Zoe, password and confirmation guards still run first, and delivery stays text-first with the existing read-aloud offer. No UI/spec change and no new bridge action. Regression executes decide and _handle_turn with TypeSafe and command routing set to raise if reached, including copied text containing “and set a timer”.

Focused suite: 137 passed. Full suite: 1889 passed, 1 skipped. CI Python 3.9/3.12 green in push run 41326964055 and PR run 41326967131.

Live computer-use test: rebuilt py2app alias bundle in this checkout, quit/relaunched, verified Ready. English copy removed Translate. Spanish copy showed Translate. It remained visible at 15.750 s; at 27.680 s it was gone and no conversation had started. Copied the original failing sample again and clicked Translate. Normal typed turn was visible and the reply was “The meeting will be tomorrow and all the documents are ready. Want me to read it out loud?” Play audio / No thanks buttons appeared. Log: translate chip shown/expired/clicked, then llm reply; no timer_set. Screenshots in attempt-2, numbered by stage. PASS for requested copy/20-second offer/invocation gate. The timing brackets the configured 20-second expiry; unit tests cover the exact boundary. No real password-manager credentials used.

All builds and computer-use actions used /Users/fernandoceja/Developer/hey-jev. Local .env retained JEV_TTS_PROVIDER=VOICESTUDIO. Feature branch lacks the unpublished VoiceStudio code by design; it remains on local main.

Claude Code Studio / Jev thread: start STATUS posted and acknowledged; 8a SPEC READY received and queued. Attempt 1 failure/attempt 2 status posted. Final status follows merge/rebuild verification.

## Standing proactive-fix rule

Failures are work orders. Diagnose and state a specific hypothesis before editing. Fix on the feature's own branch, never main; an existing main revert stands until the fix passes focused tests, full suite, CI and live computer use. Up to three distinct fix attempts; after the third failure leave main clean and preserve/document branch work. Behavior/UI/spec changes go to Claude as QUESTION; code root causes are handled autonomously. On full pass, merge/push/rebuild/relaunch without asking Fernando.

Every new feature branch starts from clean main. Before every merge list git log main..<branch> and check all commits belong to the feature; foreign commits or conflicts stop the merge. Never force-push.
