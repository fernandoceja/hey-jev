# iPhone bridge: QR pairing and read-only phone summaries (design for review)

Status: **design only, no code written.** Review this before any code. Nothing here changes behaviour until a PR is approved.

Constraints from Fernando: free only. No CloudKit, no Apple push, no local servers or listening sockets, no vendor clouds. ntfy is optional and off by default. Jev's standing guardrails still apply: no money-moving commands and no My Love on the bridge, every bridge command allowlisted, keys in the Keychain, no bridge security changes without review (this document is that review).

## 1. Where we are today

`commands/bridge.py` already gives the phone a command path with no listening socket:

- The phone drops a JSON file in `iCloud Drive/Jev/inbox`. The Mac polls the folder every 2 s, runs the command if it is on `BRIDGE_ALLOW`, writes a reply to `iCloud Drive/Jev/outbox`, and deletes the inbox file.
- One shared secret, `JEV_BRIDGE_SECRET`, lives in the Mac Keychain (set by running `python siri.py --bridge-secret`). Each file carries `cmd`, `ts`, `nonce` and `sig = HMAC-SHA256(secret, cmd|ts|nonce)`.
- Checks: signature, timestamp within 120 s, nonce not seen (the last 200 are remembered), command length at most 2000, command on the allowlist, not a confirmation command, no message reads. Replies are deleted after 10 minutes.
- The comment in `config.py` says the phone shortcut "is not built yet". So the phone side does not exist, and today's pairing is a secret typed by hand.

What this design adds: a safe way to **get the secret onto the phone**, a phone-side signer, signed replies, and **read-only summaries** the phone can show. It adds no new command types and no network client.

## 2. The phone-side constraint (the main decision)

The signature is HMAC-SHA256. iOS Shortcuts has no HMAC action (its Hash action is a plain hash, and "hash of key plus message" is not an HMAC and is open to length-extension). So a bare Shortcut cannot sign.

Recommended, free: **Shortcuts plus the free Scriptable app.** A Shortcut scans the QR code ("Scan QR/Barcode" action) and passes the text to a Scriptable script. The script stores the secret, builds and signs inbox files, and reads outbox and summary files, using a small pure-JavaScript SHA-256 HMAC (a CryptoJS-style module kept in the script). Scriptable is a third-party app; its Keychain and iCloud Drive file access and its Shortcuts hook must be **verified against its own documentation before coding** (I found App Store and community pages, not the developer docs).

Alternatives if Scriptable is rejected: a Safari "Run JavaScript on Web Page" action (needs a secure context for WebCrypto, so likely awkward), or a small sideloaded Swift app (the free personal team expires every 7 days, so not really free to live with). Decision needed (section 9).

## 3. QR pairing secret: create, store, rotate

**Create.** In Jev Settings, **Pair iPhone** makes one new secret per phone: 32 random bytes from `secrets.token_bytes`, plus an 8-byte pairing id. The QR holds `jev-pair-1`, the pairing id, the secret (base64url) and an expiry. It is shown only after the click, for 120 s, with a countdown.
- The QR window is created so screen capture cannot read it (the same `NSWindowSharingNone` approach the capture glimmer uses), it takes no clicks, and it closes on success, on Esc, or at expiry. The secret travels by camera only and never goes into iCloud.
- The secret is not shown as text, logged, or put on the clipboard.

**Store.**
- Mac: one Keychain item per phone (account `JEV_BRIDGE_PAIR_<id>`), plus a small non-secret list (id, name, paired date, last seen) in Application Support. Not in `.env`, not in files.
- Phone: Scriptable's Keychain on that phone (to be verified as device-local, not iCloud-synced).

**Pair completes.** The phone writes a signed `ack` file (its name and id) to the inbox. The Mac checks the signature and that the pairing id is waiting and unexpired, then marks the phone paired and discards the single-use pairing window. A second ack for the same id is rejected. Maximum 3 phones.

**Rotate and revoke.**
- **Revoke** (Settings, per phone or "Revoke all"): deletes the Keychain item at once. The next file from that phone fails verification. "Revoke all" also clears the nonce store and deletes the summary files.
- **Rotate**: pair again with a new QR (new secret, new id), then revoke the old one. There is no silent automatic rotation, since it needs a camera scan. Jev shows a gentle reminder after 180 days.
- The old single global `JEV_BRIDGE_SECRET` keeps working during a transition (v1 files below), then is removed in a later PR.

## 4. Signed single-use files

**Inbox file (phone to Mac), version 2:**

```json
{"v": 2, "kind": "cmd", "pid": "<pairing id>", "cmd": "what's the weather",
 "ts": 1731372000, "nonce": "<16 to 22 chars, A-Z a-z 0-9 _ ->", "sig": "<hex>"}
```

- `kind` is `cmd`, `ack` (pairing) or `req` (ask for fresh summaries). Nothing else is accepted.
- `sig = HMAC-SHA256(secret, "jev-bridge-v2|" + kind + "|" + pid + "|" + cmd + "|" + ts + "|" + nonce)`. The fixed prefix and the `kind` keep a signature from one purpose being reused for another, and `pid` ties it to one phone.
- v1 files (the current format) are still accepted for the legacy secret during the transition.

**Mac checks, in order:** regular file only (no symlinks), at most 4 KB, valid JSON and fields, known `pid`, signature (constant-time compare), `ts` within 120 s, nonce unused, command length, `cmd` on `BRIDGE_ALLOW`, not a confirmation command. Anything else is refused with a generic reply and the file is deleted.

**Replay protection (a change).** Today the last 200 nonces are remembered, and a bad-signature nonce is also remembered. Someone who can write to the iCloud folder could flood 200 files to push a real nonce out and replay a captured command inside its 120 s window. New rule: remember every nonce for **at least 5 minutes** (more than twice the window), pruned by age, not by count, and do **not** record nonces from unsigned or badly signed files. A file older than 120 s is refused whatever its nonce.

**Expiry.** The Mac's own 120 s window is the only validity rule. The file carries no `exp`, since a sender-chosen expiry could be set far out. Outbox replies still expire after 10 minutes.

**Reply file (Mac to phone)** now carries `sig = HMAC-SHA256(secret, "jev-bridge-v2|reply|" + pid + "|" + nonce + "|" + ok + "|" + reply)`. The phone script verifies it before showing the text, so a fake "done" planted in iCloud is rejected.

## 5. Read-only summaries for the phone

A folder `iCloud Drive/Jev/summaries/` written by the Mac, a few files, each signed, versioned, with a `generated` time, at most 16 KB. The phone shows "Jev's Mac is asleep" when a file is older than 15 minutes. Written only while Jev is running, and only when the user has turned summaries on in Settings (**off by default**).

**Goes in (small and already phone-askable):**
- `today.json`: date, weather one-liner, next event time and title, today's shift, due-list titles, battery percent. These match commands already on `BRIDGE_ALLOW` (`info_today`, `info_next_event`, `info_due`, `info_battery` and so on), so no new kind of data is exposed.
- `recent.json` (a second toggle, off by default): the last 10 turns **whose action is on `BRIDGE_ALLOW`**, as time, the command text and a reply summary of at most 240 characters. Turns that went to the AI model, and everything else, are excluded.

**Never leaves the Mac, in any file:**
- Secrets: every Keychain item and API key, pairing secrets, anything from the password commands.
- Attachments and captures: screenshots, recordings, files, their paths, and cleanup or storage-scan results.
- Message content (Messages, Mail, My Love) and the Eney-style "memory" equivalents: notes bodies, the dictionary and vocabulary, dictation history, clipboard history.
- Money details. The spoken `info_rent`, `info_bills` and `info_payday` replies stay ephemeral (10 minutes in the outbox) and are not written into the persistent summary files.
- Anything not on an explicit summary allowlist. A new summary field needs a new reviewed entry, like `BRIDGE_ALLOW`.

Why persistent files are stricter than replies: they sit in iCloud until replaced, so they carry less than a 10-minute reply could.

## 6. What changes in Jev's security model

| Area | Today | After this design |
|---|---|---|
| Secret | One global Keychain item, typed in by hand | One Keychain item per phone, from a single-use QR, individually revocable. Legacy secret kept only during transition |
| Signature | HMAC over `cmd, ts, nonce` | HMAC over `version, kind, pid, cmd, ts, nonce`, with domain separation. Replies signed too |
| Replay | Last 200 nonces; bad-signature nonces also stored | Every valid nonce kept at least 5 min, pruned by age; unsigned or bad files never stored |
| File types | `cmd` only | `cmd`, `ack`, `req` (inbox); reply and signed summaries (outbox side) |
| Commands | `BRIDGE_ALLOW` | **Unchanged.** No new command, no confirmation commands, no money-moving, no My Love, no message reads |
| Network | None (iCloud files only) | **None.** No listening socket, no outbound client, no new service. The Mac reads and writes a local iCloud Drive folder |
| Data to the phone | Spoken replies, 10 min | Replies plus optional signed summaries from an explicit allowlist |
| UI | None | Pair iPhone sheet, paired-phone list (name, last seen), Revoke and Revoke all, summaries toggles |

Threat notes:
- **iCloud account compromise.** An attacker with iCloud access can read plain inbox, outbox and summary files, but cannot run a command or forge a reply without a phone's secret. Mitigations: minimal summaries, Apple's Advanced Data Protection (user's choice), and optional payload encryption later (needs a cipher on both sides, so a second step).
- **Lost phone.** Revoke it from the Mac at once. The secret never travels over iCloud or the network.
- **Clock skew.** More than 120 s apart yields a clear "too old" reply. No loosening.
- **Mac asleep.** Files wait. A valid file that is already stale is refused, and the phone is told.

## 7. Optional: ntfy (off by default)

Only to say "Jev replied". Settings toggle with a plain disclosure. The Mac makes one outbound HTTPS POST to a random topic derived from the pairing secret (so it cannot be guessed), with a fixed title and **no content**. The free ntfy iPhone app shows it. No listening socket on the Mac. ntfy's service sees the topic, the timing and the IP address, but not the reply. Nothing depends on it: without it the phone just reads the outbox, which already works.

## 8. Costs

All free: iCloud Drive (already used), Shortcuts, and Scriptable (free app). No paid Apple Developer membership, no server, no subscription.

## 9. Decisions needed from Fernando

1. Phone runtime: **Scriptable** (recommended), or another route from section 2.
2. Summaries: on at all? Which of `today.json` and `recent.json`? Keep both off by default?
3. Where Pair iPhone lives (Settings page, plus a Quick Command?) and whether pairing also asks for Touch ID on the Mac.
4. How long to keep the legacy v1 secret path (suggested: one release, then remove).
5. Payload encryption: now, later, or not at all.

## 10. Build order (when approved, one small PR each, tests and local suite first)

1. Time-based nonce store and v2 verification, with the replay fixes (no UI).
2. Per-phone Keychain store, pairing ack, revoke, and the QR sheet.
3. Signed replies and the summaries writer, toggles off by default.
4. The Scriptable script and Shortcut, with a setup guide (docs only).
5. Optional ntfy nudge.
