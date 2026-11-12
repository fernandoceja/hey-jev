# iPhone bridge: QR pairing (design, updated with Fernando's answers)

Status: **design only. No pairing code is written, and none will be until Fernando approves this updated document.** Replay protection (section 4) is already fixed and merged (#149). Everything else here is a plan.

Constraints: free only. No CloudKit, no Apple push, no local servers or listening sockets, no vendor clouds. ntfy is an optional later extra, off by default. Standing guardrails still apply: no money-moving commands and no My Love on the bridge, every bridge command allowlisted, keys in the Keychain, no bridge security change without review (this document is that review), and nothing is deleted without being asked.

## 1. Where we are today

`commands/bridge.py` gives the phone a command path with no listening socket:

- The phone drops a JSON file in `iCloud Drive/Jev/inbox`. The Mac polls every 2 s, runs the command if it is on `BRIDGE_ALLOW`, writes a reply to `iCloud Drive/Jev/outbox`, and deletes the inbox file.
- One shared secret, `JEV_BRIDGE_SECRET`, lives in the Mac Keychain (set with `python siri.py --bridge-secret`). Each file carries `cmd`, `ts`, `nonce` and `sig = HMAC-SHA256(secret, cmd|ts|nonce)`.
- Checks: signature, timestamp within 120 s, nonce unused, command length at most 2000, on the allowlist, not a confirmation command, no message reads. Replies are deleted after 10 minutes.
- The phone side does not exist yet ("the phone shortcut is not built yet" in `config.py`), so today's pairing is a secret typed by hand.

This design adds a safe way to **get a secret onto the phone**, a phone-side signer, and signed replies. It adds no new command types and no network client.

## 2. The phone runtime: Scriptable, with a gate (decision made, not fully confirmed)

iOS Shortcuts has no HMAC action (its Hash action is a plain hash, and "hash of key plus message" is not an HMAC and is open to length-extension). So the phone needs a small script runtime. **Fernando's answer: Scriptable is OK, but only after its Keychain and iCloud file access are confirmed from Scriptable's own documentation.** I read the developer documentation at docs.scriptable.app. Result: **confirmed in part, not fully. So the rule stands: no phone-side code until the gaps below are closed.**

**Confirmed from Scriptable's own docs:**
- **Keychain exists.** `Keychain.contains(key)`, `set(key, value)`, `get(key)` (throws if missing) and `remove(key)`, string values, described as stored "in an encrypted database".
- **iCloud file access exists.** `FileManager.iCloud()` returns a file manager for iCloud, with `read`, `readString`, `write`, `writeString`, `listContents`, `fileExists`, `createDirectory`, `joinPath`, plus `isFileDownloaded` and `downloadFileFromiCloud` for files not yet local.
- **Access outside Scriptable's own folder is by file bookmarks.** Bookmarks made in Scriptable's settings work only when a script runs inside the app. From Shortcuts or Siri the bookmark must be made with Scriptable's "Create File Bookmark" Shortcuts action.
- **Shortcuts hand-off exists.** Input arrives as `args.shortcutParameter` or `args.plainTexts`. Output goes back with `Script.setShortcutOutput(value)` (text, number, boolean or dictionary).
- **Modules exist.** `importModule('name')` loads another script file, so a signing helper can live in its own file.

**Not confirmed, and it matters:**
1. **Whether the Keychain is device-only or syncs through iCloud Keychain.** The Keychain page does not say. If it synced, the pairing secret would be copied to the user's other devices (end-to-end encrypted by Apple, but not "this phone only"). Needs a test on the iPhone, or Fernando accepts that.
2. **Whether a bookmark can point at `iCloud Drive/Jev/` (outside Scriptable's own folder) and be read and written from a script run by Shortcuts.** The docs describe bookmarks for "files and folders outside Scriptable's documents directory" in general but do not say this exact case works. Needs a test on the iPhone.
3. **Scriptable has no crypto, hash or HMAC API at all.** The 60-entry API index lists none (it has `Data`, `Keychain`, `FileManager`, `Request`, `UUID` and so on). So the HMAC-SHA256 must be our own small pure-JavaScript module (kept in a script and loaded with `importModule`), and it needs its own known-answer tests on the Mac. The phone also has no documented random-byte API, so nonces would come from `UUID` plus the timestamp (a nonce must be unique, not secret).

**Fallback if (2) fails:** point the bridge folders at Scriptable's own iCloud folder instead of `iCloud Drive/Jev`. That avoids bookmarks, but it is unverified: no Scriptable iCloud container exists on this Mac to check, so the Mac-side path is unknown.

**Gate before any phone-side code:** a short manual device test on Fernando's iPhone: (a) a Shortcut-run script reads and writes a file in `iCloud Drive/Jev/inbox` through a bookmark, (b) a Keychain value stays on that phone (or Fernando accepts that it syncs), (c) the pure-JS HMAC matches the Mac's known-answer values. Until (a) to (c) pass, only Mac-side work can be planned. If Scriptable fails, the alternatives are a Safari "Run JavaScript on Web Page" action or a sideloaded Swift app (7-day personal-team expiry, so not really free).

## 3. QR pairing: create, store, rotate

**Where it lives (decision):** Jev's **Settings** only, a "Pair iPhone" button. **Touch ID is asked before the QR is shown**, every time (no cached approval). Jev uses Apple's standard device-owner authentication (Touch ID, with the system's own Mac-password fallback). Jev never sees or handles a password, and never clicks the prompt. Fernando clicks it.

**Create.** After the Touch ID prompt succeeds, Jev makes one new secret per phone: 32 random bytes from `secrets.token_bytes`, plus an 8-byte pairing id. The QR holds a format tag, the pairing id, the secret (base64url) and an expiry. It shows for 120 s with a countdown.
- The QR window is created so screen capture cannot read it (the same `NSWindowSharingNone` approach the capture glimmer uses), takes no clicks, and closes on success, on Esc, or at expiry. The secret travels by camera only and never goes into iCloud.
- The secret is never shown as text, logged, or put on the clipboard.

**Store.**
- Mac: one Keychain item per phone (account `JEV_BRIDGE_PAIR_<id>`), plus a small non-secret list (id, name, paired date, last seen) in Application Support.
- Phone: Scriptable's Keychain (see the open question in section 2).

**Pair completes.** The phone writes a signed `ack` file (its name and id) to the inbox. The Mac checks the signature and that the pairing id is waiting and unexpired, marks the phone paired and discards the single-use pairing window. A second ack for the same id is rejected. Maximum 3 phones.

**Rotate and revoke.**
- **Revoke** (Settings, per phone or "Revoke all") makes the Mac stop trusting that phone's secret at once, so its next file fails verification. Removing the Keychain item is part of revoke and is shown as such; Jev asks before it removes anything.
- **Rotate** means pairing again with a new QR (new secret, new id), then revoking the old one. No silent automatic rotation, since it needs a camera scan. Jev shows a reminder after 180 days.

**The old shared secret (decision): keep it for 7 days after a phone pairs, then retire it.**
- The 7 days start when the **first** phone's pairing completes. During that time old-format (v1) files signed with `JEV_BRIDGE_SECRET` are still accepted.
- After 7 days Jev **stops accepting v1 files**. Settings shows the countdown and a "Retire now" button for anyone who wants it earlier.
- Retiring only stops Jev from accepting the old secret. **Removing the old Keychain item is a separate, explicit step Fernando clicks ("Remove old secret").** Nothing is deleted automatically.
- If no phone ever pairs, the old secret keeps working as it does today.

## 4. Signed single-use files

**Inbox file (phone to Mac), version 2:**

```json
{"v": 2, "kind": "cmd", "pid": "<pairing id>", "cmd": "what's the weather",
 "ts": 1731372000, "nonce": "<16 to 22 chars, A-Z a-z 0-9 _ ->", "sig": "<hex>"}
```

- `kind` is `cmd` or `ack` (pairing). Nothing else is accepted in the first version.
- `sig = HMAC-SHA256(secret, "jev-bridge-v2|" + kind + "|" + pid + "|" + cmd + "|" + ts + "|" + nonce)`. The fixed prefix and `kind` keep a signature for one purpose from being reused for another, and `pid` ties it to one phone.
- v1 files (the current format) stay valid for the old secret during the 7-day window above.

**Mac checks, in order:** regular file only (no symlinks), at most 4 KB, valid JSON and fields, known `pid`, signature (constant-time compare), `ts` within 120 s, nonce unused, command length, `cmd` on `BRIDGE_ALLOW`, not a confirmation command. Anything else is refused with a generic reply and the file is deleted.

**Replay protection: done (#149).** Every accepted nonce is now remembered until the end of its own timestamp window (`ts + 120 s + 1`), with no count limit. Files with a bad signature or an old timestamp record nothing, so junk files cannot push real nonces out. A replay inside the window is still refused. The v2 format keeps using this store.

**Expiry.** The Mac's own 120 s window is the only validity rule. The file carries no `exp`, since a sender-chosen expiry could be set far out. Outbox replies still expire after 10 minutes.

**Reply file (Mac to phone)** gets `sig = HMAC-SHA256(secret, "jev-bridge-v2|reply|" + pid + "|" + nonce + "|" + ok + "|" + reply)`. The phone script verifies it before showing the text, so a fake "done" planted in iCloud is rejected.

## 5. What changes in Jev's security model

| Area | Today | After this design |
|---|---|---|
| Replay | Last 200 nonces; junk could push real ones out | **Fixed in #149:** every accepted nonce kept until its window ends |
| Secret | One global Keychain item, typed in by hand | One Keychain item per phone, from a Touch ID-gated single-use QR, individually revocable. Old secret accepted for 7 days after the first pairing, then retired (removal is a separate click) |
| Signature | HMAC over `cmd, ts, nonce` | HMAC over `version, kind, pid, cmd, ts, nonce` with domain separation. Replies signed too |
| File types | `cmd` only | `cmd` and `ack` in; signed replies out |
| Commands | `BRIDGE_ALLOW` | **Unchanged.** No new command, no confirmation commands, no money-moving, no My Love, no message reads |
| Network | None (iCloud files only) | **None.** No listening socket, no outbound client, no new service |
| UI | None | Settings: Pair iPhone (behind Touch ID), paired-phone list, Revoke and Revoke all, legacy countdown with Retire now and Remove old secret |

Threat notes:
- **iCloud account compromise.** An attacker with iCloud access can read plain inbox and outbox files, but cannot run a command or forge a reply without a phone's secret. Payload encryption is **out of this version** (below).
- **Lost phone.** Revoke from the Mac at once. The secret never travels over iCloud or the network.
- **Clock skew.** More than 120 s apart gives a clear "too old" reply. No loosening.
- **Mac asleep.** Files wait. A valid file that is already stale is refused and the phone is told.

## 6. Later options (not in the first version)

**Phone summaries.** **Decision: off by default, and not part of the first version.** The allowlist below is kept as a later option. If it is ever built, it is a separate reviewed PR, behind a Settings toggle that starts off.
- A folder `iCloud Drive/Jev/summaries/` of signed, versioned JSON files, each at most 16 KB, stale after 15 minutes ("Jev's Mac is asleep").
- *Could go in:* `today.json` (date, weather one-liner, next event time and title, today's shift, due-list titles, battery percent; all already phone-askable through `BRIDGE_ALLOW`), and a second, separate toggle for `recent.json` (the last 10 turns whose action is on `BRIDGE_ALLOW`, command text plus a reply summary of at most 240 characters).
- *Never leaves the Mac, in any file:* secrets and every Keychain item; attachments, captures, files and their paths, cleanup or scan results; message content (Messages, Mail, My Love) and notes bodies, the dictionary, dictation and clipboard history; money details (rent, bills and payday replies stay ephemeral in the outbox); and anything not on an explicit summary allowlist.

**Payload encryption.** **Decision: out for this version; noted as a future option.** It would hide command and reply text from anyone with access to the iCloud files. It needs an authenticated cipher on both the Mac and the phone (Scriptable has none, so it would be another hand-written module with its own tests), so it is a second step with its own review.

**ntfy nudge.** Optional, off by default, free: one outbound HTTPS POST from the Mac to a random topic with a fixed title and no content, shown by the free ntfy iPhone app. No listening socket. Nothing depends on it.

## 7. Costs

All free: iCloud Drive (already used), Shortcuts, and Scriptable (free app). No paid Apple Developer membership, no server, no subscription.

## 8. Decisions (answered by Fernando)

1. **Phone runtime:** Scriptable is OK, but only once its Keychain and iCloud file access are confirmed from its own documentation. *Result:* confirmed in part (section 2). Two things are unconfirmed and one needs our own code, so **no phone-side code until the device test passes.**
2. **Summaries:** off by default; the allowlist stays in this document as a later option (section 6).
3. **Pair iPhone:** in Jev's Settings, behind Touch ID before the QR shows. Fernando clicks the prompt.
4. **Old shared secret:** keep for 7 days after a phone pairs, then retire it (stop accepting it); removing it from the Keychain is a separate, explicit click.
5. **Payload encryption:** out for this version; a future option.

## 9. Build order (when this document is approved; one small PR each, local suite first)

1. ~~Time-based nonce store and replay fixes~~ **Done (#149).**
2. Manual iPhone device test of Scriptable (section 2 gate). No code; Fernando runs it, or approves a test script to run.
3. v2 verification on the Mac, per-phone Keychain store, pairing `ack`, revoke, and the legacy 7-day timer (no UI yet), with tests.
4. Settings: Pair iPhone with the Touch ID prompt, the QR window, the paired-phone list, Retire now and Remove old secret.
5. Signed replies.
6. The Scriptable script and Shortcut, with a setup guide, only after step 2 passes.
7. Later, each its own review: summaries, ntfy, payload encryption.
