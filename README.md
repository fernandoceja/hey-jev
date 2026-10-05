# Hey Jev

A voice assistant for your Mac. Say "Hey Jev" or hold right Option, say a thing, it does it and answers back.

- **Jev** (TypeSafe) makes a decision in one call when the phrase isn't a local command, $0.00004 per request
- **Fish Audio S2.1 Pro** speaks replies, with emotion tags like `[chuckling]` and `[sighing]`. Messages from My Love are the exception: the Mac `say` command speaks those, and the text never goes to Fish
- **Whisper** (local, faster-whisper) turns your voice into text
- An LLM only wakes up for a general question. Weather, the date, the calendar, notes, and the other local commands below are answered on the Mac, before any API call

**Mac only.** Works on macOS Sequoia and Tahoe. It controls the Mac through AppleScript and the Keychain, so it won't run on Windows or Linux.

## What it can do

Open, quit, hide, minimise or switch to apps, open a new browser tab or a website ("open youtube.com in Brave"), Mac volume up / down / mute / set, Apple Music play / pause / next / previous / what's playing, dark mode, lock or sleep the Mac. Spotify volume and playback stay available only when the Spotify app is installed and you name Spotify. Two things in one sentence work too: "pause the music and open Notes".

### Adding apps

Add, remove or fix apps in the **Apps** tab of the window, then restart Jev. They're saved to `apps.json`, where you can also add a line by hand like `"notion": "Notion"` (the name you say, then the app's name in /Applications) and restart. For apps the transcriber gets wrong, use the longer form with a `heard_as` list:

```json
"claude_code": {"app": "Claude", "say": "Claude Code", "heard_as": ["cloud code", "clawed code"]}
```

Open and quit work for any installed app, not just a fixed list. "Open cap cut", "launch ChatGPT", "start Cursor", and "open the Claude app" are matched against `/Applications`, `/System/Applications` (including Utilities), and `~/Applications`. Quit is a polite quit. It will not quit Finder or Hey Jev. "Quit all" asks you to say yes within about 10 seconds, and it has to be its own command.

Time and date are answered on the Mac: "what time is it", "what's the date", "what day is it". Calendar is read-only, across every calendar in Apple Calendar: "what's next", "what's my schedule today", "when's my next meeting", "what's on my calendar", "when's my next shift". A shift is the next event in the next 14 days whose title contains R345, Apple, Brea, or shift. "What apps are open" lists the apps in the foreground.

"What's today" is the date plus how many events are on today's calendar. "What's Zoe got tomorrow" reads tomorrow's events whose title or calendar mentions Zoe, school, or Cabrillo.

Shortcuts run only from a Shortcuts folder named `Jev`: "run shortcut Leaving for work", "run my Focus shortcut", "do Jev morning", or "run Leaving for work" when that name is actually in the folder. `shortcuts list --folder-name Jev` prints every shortcut on the Mac when that folder does not exist, so Hey Jev checks `shortcuts list --folders` first and compares identifier lists before it runs anything. If the folder is missing or the listing can't be verified, nothing runs.

These are also answered on the Mac, with no TypeSafe or LLM call:

- **Weather:** "weather", "what's the weather". Current conditions, high, low, and chance of rain for Upland, CA, from Open-Meteo. No API key. If the request takes more than about 4 seconds, or it fails, she says she couldn't check the weather.
- **Brief me:** the date, that weather, today's events, the next shift, and the first few items from the due list. On an Apple payday, an IHSS deposit date, or an IHSS timesheet day, she adds that reminder. Gmail is an optional step. It stays off unless a Google OAuth token is stored in the Keychain under service `com.jevsiri.keys`, account `GOOGLE_OAUTH_TOKEN`. This build does not include a Google client library and does not call Google. `gmail_brief_line()` in `commands/weather.py` is the stub to replace if you add that later.
- **Messages from My Love:** "check my messages from My Love". Reads the latest 3 incoming messages from the handles in `commands/config.py` (`MY_LOVE_HANDLES`: `+15623616724` and `cgarcilazo6724@icloud.com`). When the `text` column is empty, the body is decoded from `attributedBody`. She speaks them with the Mac `say` command only. They are not sent to Fish Audio, TypeSafe, or an LLM, and the iPhone bridge will not run this command. Full Disk Access is optional and is the only reason to grant it. Without it, she says how to turn it on.
- **Notes:** "take a note: buy oat milk" appends a timestamped line to `~/Documents/Jev/notes.md`, creating the file if needed.
- **Due this week:** "what's due this week" reads `~/Documents/Jev/due.md`. See the format below.
- **Focus:** "start focus mode" or "start focus mode for 10 minutes" runs the shortcut `Jev Focus On`, then a timer. The default is 25 minutes. When it ends, she runs `Jev Focus Off` and says focus is off. Hey Jev has to stay open for the off shortcut. Both shortcuts must live in the Jev folder. See below.
- **IHSS hours:** "log IHSS hours: 4 hours today" or "log IHSS hours: 3.5 hours yesterday" appends `date,hours` to `~/Documents/Jev/ihss_hours.csv` and says the total for the current semi-monthly period (the 1st through the 15th, or the 16th through the end of the month).
- **Case status:** "check my case status" opens https://egov.uscis.gov/casestatus in Google Chrome. No receipt number is stored.
- **iPhone:** commands can arrive as signed files in iCloud Drive. There is no network listener. See below.

Timers and reminders: "set a timer for 5 minutes", "remind me in 20 minutes to call Mum", "how long is left?", "cancel the timer". Each one counts down live in the window, and she tells you when it's done. A focus timer is one of these: when it finishes she turns focus off. "Start a 5 minute timer for Zoe" is a local timer labeled Zoe, so it does not ask the LLM to write the alert.

## Round 2 commands

These are chosen from the transcript before any TypeSafe or LLM call. A sentence that only resembles one of them ("how long until summer", "help me write an email", "what's the weather in paris") still goes to the LLM. Edit the maps in `commands/config.py`: `KNOWN_APPS`, `APP_NICKNAMES`, `SITE_CONFIG`, and `SHIFT_TITLE_PATTERNS`.

- **Apps.** "Open settings", "open business email", "open my phone", "open numbers", "open clean my mac". Nicknames live in `APP_NICKNAMES` (business email and Zoho are Zoho Mail - Desktop, my phone and mirroring are iPhone Mirroring, numbers and budget app are Numbers Creator Studio, settings is System Settings). She launches with `open -a` and says the app isn't installed when that fails.
- **Sites, in Google Chrome.** WorkJam, UKG (`https://sso.prd.mykronos.com`), the Apple employee portal (`https://people.apple.com/`), UMGC (`learn.umgc.edu`), Shopify admin, Shopify orders (`https://admin.shopify.com/store/80-s-obsession-company/orders`), the store site, Cal.com bookings, the IHSS timesheet portal (`https://etimesheets.ihss.ca.gov/login`), USCIS case status, Bank of America, Fidelity, Capital One, and GitHub. She does not fetch those pages, and she does not sign in.
- **Apple Music.** "Play", "pause", "next track", "previous track", "what's playing". "Play Bohemian Rhapsody on YouTube" opens a YouTube search in Chrome. "Pause Spotify" still talks to Spotify when that app is on the Mac.
- **Shifts.** "When's my next shift", "am I working this weekend", "how long is my shift". A shift is a calendar event whose title matches `SHIFT_TITLE_PATTERNS` (an R-number such as R345, the word shift, Brea, or Apple). "When do I start at Brea" reads a Brea line in `due.md`, and a Brea event on the calendar when there is one.
- **Shift override.** "My shift Monday is 9:30 to 6:30 at Brea" saves that day in `~/Library/Application Support/Hey Jev/shift-overrides.json`. It is a plain file: the date, the start, the end, and the place. No password and no WorkJam login. That date replaces the calendar shift. Other days still come from the calendar. "Clear my shift Monday" removes one day. "Clear my shift overrides" removes all of them. A weekday means the next one, including today. "9:30 to 6:30" with no am or pm is 9:30 AM to 6:30 PM.
- **When to leave.** "When should I leave for work" uses the next Brea shift, including a saved override. Leave time is the shift start, minus the drive, minus `LEAVE_BUFFER_MINUTES` (15). The drive is Apple MapKit (`MKDirections` expected travel time, with traffic for that arrival). No API key, and nothing is added to the Keychain. Home and the store are `HOME_ADDRESS` and `BREA_STORE_ADDRESS` in `commands/config.py`: Upland, CA, to Apple Brea Mall, 1016C Brea Mall, Brea, CA 92821. Apple's own store page lists 1016C. 1065 Brea Mall is the mall building, not the Apple suite. If MapKit is missing or the request fails, she uses `LEAVE_TYPICAL_DRIVE_MINUTES` (35) and says it is an estimate.
- **School.** "What's due for UMGC" or "what's due for school" reads `due.md` lines that mention UMGC, school, or class, or that carry `#umgc`, `#school`, or `#class`, for the next 30 days.
- **Money, read-only.** "When's rent due" and "what bills are coming up" read `due.md` only. "How long until payday" uses `~/Documents/Jev/money.md` when that file exists, otherwise a default: Apple every other Friday anchored on 2026-09-25, and IHSS on the 15th and the last day of the month. She never opens a bank from these questions. Opening a bank site is a separate "open Bank of America" command, and that only launches Chrome.
- **Payday sweep, date only.** "What's due today", "payday check", or "any reminders today" looks at the calendar, not a bank. On an Apple Friday she says "Apple payday today — move $600 to Zoe …4157." On the 15th or the last day of the month she says the same kind of line for IHSS. If both land on one day, she names both in one line. The 14th and the last day of the month also get "Time to submit your timesheet." A day that is none of those is silent inside "brief me", and the check command says nothing is due to sweep. The amount and the account label are `SWEEP_AMOUNT` and `SWEEP_ACCOUNT_LABEL` in `commands/config.py`. The Apple Friday is `DEFAULT_APPLE_PAY_ANCHOR` there, or `apple:` in money.md. The first launch of Hey Jev on a sweep day speaks the line once. The date is stored in `~/Library/Application Support/Hey Jev/sweep-spoken.txt`, so opening the app again that day does not repeat it. She does not look up a balance and she does not move the money.
- **IHSS.** "Log 3 hours for grandma" appends to `ihss_hours.csv`, same as "log IHSS hours". "How many hours this pay period" totals the current 1st–15th or 16th–end period. "Remind me to submit my timesheet" creates a Reminders item titled Submit IHSS timesheet and says so.
- **The LLC.** "Open Shopify admin", "open bookings", "open the store site", "any new orders" (opens `https://admin.shopify.com/store/80-s-obsession-company/orders`), "open business email".
- **Zoe.** "What's Zoe got tomorrow", "open Princess Academy" (runs the shortcut `Zoe's Princess Academy` when it is in the Jev folder, otherwise opens `https://fernandoceja.github.io/Zoe-s-Princess-Academy/`), "start a 10 minute timer for Zoe".
- **The Mac.** Volume up, down, and set, mute and unmute, brightness up and down, battery level, lock the screen, screenshot to the Desktop, show the desktop, and open Downloads, Documents, or the Desktop folder. "Empty the trash" asks you to say yes first, and it has to be its own command.
- **Matrix.** "Blue pill", "take the blue pill", or "matrix mode" opens Terminal full screen and runs `cmatrix` (green rain) through your default shell. "Red pill" or "take the red pill" quits that cmatrix and closes the Terminal window Jev opened for it. Other Terminal windows stay open. If that window also has unrelated tabs, only the Matrix tab is closed. If `cmatrix` is not installed, she says to run `brew install cmatrix` and does not open Terminal. This stays on the Mac. The iPhone bridge will not run it.
- **ChatGPT.** "Continue ChatGPT" brings ChatGPT to the front and types the word continue, then Return.
- **Shortcuts.** "Run shortcut Leaving for work" or, when the name matches a shortcut that was verified in the Jev folder, "run Leaving for work".
- **Help.** "What can you do" lists those categories in one short reply.

### money.md

Optional. Without it, payday uses the default Apple Friday and the IHSS 15th / month-end dates, and she says so.

```markdown
# Jev only reads this file. It does not open a bank.

apple: 2026-09-25
ihss: semi-monthly
```

`apple:` is one payday, and it should be a Friday. The next payday is every 14 days from that date. The $600 sweep and the "Zoe …4157" label are not read from this file. Change those in `commands/config.py`.

### Shift titles and the due list

Add a pattern to `SHIFT_TITLE_PATTERNS` in `commands/config.py` if a store name should count as a shift. School and bill questions also look at tags on the due line:

```markdown
- 2026-10-01 Pay rent
- 2026-10-03 Start at Brea
- 2026-10-05 UMGC discussion post #umgc
- 2026-10-08 Electric bill #bill
```

## Due list

`~/Documents/Jev/due.md` is a markdown list you maintain yourself. One item per line. Each item needs a date written `YYYY-MM-DD`. The rest of the line is what she says. Blank lines, headings, and lines with no date are skipped. She reads items due today through 7 days from today, soonest first.

```markdown
# Due

- 2026-09-30 Pay rent
- 2026-10-03 Zoe permission slip
- 2026-10-12 Too far out, so this one is skipped
```

## Focus shortcuts

In the Shortcuts app, inside the folder named `Jev`, create:

1. **Jev Focus On.** Add a Set Focus action and turn your Focus on (Do Not Disturb, or whichever Focus you use).
2. **Jev Focus Off.** The same action, set to turn that Focus off.

"Start focus mode" runs the first, waits (25 minutes unless you say "for N minutes"), runs the second, and tells you. Quit Hey Jev and the off shortcut will not run, because the timer lives in the app.

## iPhone bridge

Hey Jev does not listen on the network. While it is running (the app, or `python siri.py` / `--wake`, not a one-shot `--text`), a background thread checks `~/Library/Mobile Documents/com~apple~CloudDocs/Jev/inbox/` every 2 seconds. That folder is `iCloud Drive/Jev/inbox` on the iPhone. Replies are written to `iCloud Drive/Jev/outbox`.

Each command is a JSON file:

```json
{"cmd": "what's the weather", "ts": 1710000000, "nonce": "a1b2c3d4e5", "sig": "<hex hmac>"}
```

- `cmd` is the same kind of phrase you would say out loud.
- `ts` is the unix time in whole seconds.
- `nonce` is 8 to 64 characters: letters, digits, underscore, or hyphen. Use a new one every time.
- `sig` is the hex HMAC-SHA256 of the exact string `cmd|ts|nonce` (the three values joined with `|`, no spaces around the pipes, UTF-8). `ts` in that string is the decimal digits of the integer.

The secret is only in the Mac Keychain, service `com.jevsiri.keys`, account `JEV_BRIDGE_SECRET`. A `.env` value is not used for this. Create it once:

```bash
.venv/bin/python siri.py --bridge-secret
```

That prints the secret once. Copy it into the iPhone Shortcut and do not commit it. A file is rejected when the signature is wrong, when `ts` is more than 120 seconds from the Mac's clock, when that nonce was already used, or when `cmd` is longer than 2000 characters (`BRIDGE_MAX_CMD`). The inbox file is deleted after it is handled. Quit-all, reading messages (including My Love), and anything that needs a spoken confirmation are refused. Anything that would move money is refused too. The payday check only speaks a reminder, and that one command is allowed by its own name (`info_payday_check`), not by a category. Saving a shift (`shift_set`), clearing it (`shift_clear`), and the leave-time answer (`info_leave`) are each their own allowlist name too. Reading messages (including My Love) and anything that would move money stay off. Allowed phrases are the local ones: time, date, what's today, weather, calendar, shift, a saved shift, when to leave, open apps, brief me, due, payday check, Zoe, take a note, focus, IHSS hours, and case status.

### iPhone Shortcut

1. On the Mac, run `python siri.py --bridge-secret` and copy the hex secret. Leave Hey Jev running so the inbox is polled.
2. In Shortcuts, create a new shortcut.
3. **Dictate Text.** Prompt: "What should Jev do?" Save as `Command`.
4. **Date.** Current Date. Format as Unix Time in seconds, as a whole number (no decimal). Save as `Timestamp`.
5. **Random** or **Text** for a nonce of at least 8 letters or digits, different every run. Save as `Nonce`.
6. **Text** that is exactly `Command`, then `|`, then `Timestamp`, then `|`, then `Nonce`. No spaces beside the pipes and no extra newline. Save as `Payload`.
7. **Generate Hash.** Input: `Payload`. If the action lists HMAC-SHA256, choose it, set the key to the secret from step 1, and ask for hex. Save as `Signature`.
8. If Generate Hash has no HMAC choice, install the free app **a-Shell** and add its **Execute Command** action instead. The secret is hex, so it is safe inside single quotes. The command is `printf '%s' 'PAYLOAD' | openssl dgst -sha256 -hmac 'SECRET'`. If `Command` itself contains a single quote, build the payload in a file in the shortcut and run `openssl dgst -sha256 -hmac 'SECRET' -hex` on that file. The signature is the hex after the `=` sign, with spaces removed. Save that as `Signature`.
9. **Text** the JSON, with quotes inside `Command` replaced by `\"` first (**Replace Text**). Use this shape, with your variables in the values: `{"cmd":"Command","ts":Timestamp,"nonce":"Nonce","sig":"Signature"}`. `ts` is a number, not a string. Save the file to **iCloud Drive/Jev/inbox** with the name `Nonce.json` (the **Save File** action, destination iCloud Drive, ask where to save turned off, overwrite on).
10. **Wait** 4 seconds. iCloud can be slow; if the next step misses, wait 8 seconds or repeat the wait a couple of times.
11. **Get File** `iCloud Drive/Jev/outbox/Nonce.json`.
12. **Get Dictionary from Input**, then **Get Dictionary Value** for the key `reply`.
13. **Speak Text** that reply. Optionally delete the outbox file. If the shortcut never does, the Mac deletes that reply after about 10 minutes.

The Mac also speaks the reply while the shortcut reads it back. Message text is never written to the outbox. Each inbox poll, and the moment the bridge thread starts, deletes reply files in that outbox that are older than 10 minutes (`OUTBOX_TTL_SECONDS` in `commands/config.py`). Only a regular file directly in the outbox, named like the nonce plus `.json`, is removed. A shortcut can still delete a reply after it reads it. It does not have to.

Dictation: say "Hey Jev, transcribe" and a little waveform bubble shows at the bottom of the screen. Talk as long as you like, then say "Hey Jev, stop transcribing" and the text is pasted where your cursor is (and left on the clipboard). It uses `gpt-4o-mini-transcribe` through your OpenRouter key, so no extra key. Every dictation is saved to `~/Library/Logs/Hey Jev dictation.jsonl`.

To fix words it gets wrong, open the **Dictionary** tab in the window: add a word and the ways it gets misheard, and it's used straight away. It saves to `vocabulary.json`, which is gitignored so your words stay private (`vocabulary.example.json` is the starter list).

**Privacy note:** dictation is optional, and it's the one feature that sends your voice off your Mac. The audio between "transcribe" and "stop transcribing" is uploaded to OpenRouter, which passes it to OpenAI's `gpt-4o-mini-transcribe`. Add an OpenAI key in Keys and it goes straight to OpenAI instead, so only one company sees it. If you don't want your audio leaving your Mac, just don't use dictation. Everything else Jev hears is transcribed locally by Whisper, and only the text of your commands after "Hey Jev" is sent to TypeSafe. Messages from My Love stay on the Mac: the `say` command speaks them, and that command is refused on the iPhone bridge. Check for updates, in Settings or the Hey Jev menu, sends one read-only request to `api.github.com` when you click it, asking whether henryklunaris/hey-jev has commits this fork does not. No token is sent. Nothing is downloaded or installed.

Anything that isn't a command ("who wrote Hamlet") goes to Claude Haiku via OpenRouter and gets spoken back. Haiku is told the current local date and time, so "tomorrow" in a reminder lines up with today.

## What you need

- A Mac
- Python 3 (tested on 3.14, see below if you don't have it)
- Apple Music, which is already on the Mac. Spotify is optional: music commands use it only when you say Spotify and the app is installed
- Three API keys:
  - **TypeSafe (Jev):** [https://typesafe.ai](https://typesafe.ai)
  - **Fish Audio:** [https://fish.audio/?fpr=henryk](https://fish.audio/?fpr=henryk). Sign in, then create a key on the API keys page in your account. You don't need a paid plan or API credit: the `s2.1-pro-free` model this app uses is free on the API until the end of November 2026.
  - **OpenRouter:** [https://openrouter.ai](https://openrouter.ai), answers questions and does dictation
  - **OpenAI (optional):** [https://platform.openai.com](https://platform.openai.com), sends dictation straight to OpenAI instead of through OpenRouter



### Don't have Python?

Check in Terminal:

```bash
python3 --version
```

If that prints a version, you're set. If not, pick one:

- **Easiest:** download the macOS installer from [python.org/downloads](https://www.python.org/downloads/) and run it.
- **With Homebrew:** `brew install python`



## Setup

```bash
git clone https://github.com/henryklunaris/hey-jev.git
cd hey-jev
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python setup.py py2app -A
open "dist/Hey Jev - Fish Audio.app"
```

The py2app line builds the app bundle in alias mode, so it runs the code straight from this folder. Build it once, and again if you move the folder or if `setup.py` changes. Calendar access is one of those `setup.py` changes: rebuild, then quit and reopen, or macOS never shows the new permission prompt. `py2app` itself is not in the runtime requirements; install it with `.venv/bin/pip install 'py2app~=0.28.9'` when you build. `0.28.10` requires Python 3.10. `requirements.txt` uses compatible-release pins (`~=`) chosen for this Python 3.9 venv. After pulling a pin change, reinstall with `.venv/bin/pip install -r requirements.txt`.

First launch:

1. The window opens on the **Keys** tab. Paste your keys and hit Save keys, they're saved in your Mac Keychain. Change them any time in the same tab.
2. Whisper downloads its `small.en` model (about 250MB), one time.
3. macOS will ask for **Microphone** access. Say yes. To use a different mic, pick it in the **Settings** tab.
4. Add "Hey Jev - Fish Audio" (or your terminal, if you run from the terminal) under **System Settings > Privacy & Security > Accessibility**, or key presses are ignored.
5. The first time it controls Music, Reminders, ChatGPT, Finder, or System Events (brightness, show desktop, dark mode, typing into ChatGPT) you'll get an **Automation** prompt. Say yes. Quitting an app does not ask once per app. Screenshots need **Screen Recording**. Rebuild with `python setup.py py2app -A` after this round so the app's Apple Events description matches; `setup.py` changed and `requirements.txt` did not.
6. The first calendar question ("what's next", "what's my schedule today", "when's my next shift", "brief me", "what's Zoe got tomorrow") asks for **Calendars → Full Access**. Allow it. That string is in the app bundle, so rebuild with `python setup.py py2app -A` after pulling a `setup.py` change, then quit and reopen. A `--text` run from Terminal asks Terminal (or Cursor) for calendar access, not the Hey Jev bundle.
7. Shortcuts need a folder named `Jev` in the Shortcuts app. Hey Jev confirms that folder with `shortcuts list --folders` before it runs anything. If the folder is missing, she will not run a shortcut, even though `shortcuts list --folder-name Jev` would print your whole library. Put **Jev Focus On**, **Jev Focus Off**, and **Zoe's Princess Academy** there if you use them.
8. **Full Disk Access is optional.** Grant it only if you want "check my messages from My Love". System Settings > Privacy & Security > Full Disk Access, add Hey Jev (or Terminal, if you use `--text`). Everything else works without it.
9. Weather calls `api.open-meteo.com` (no key). The iPhone bridge does not open a port. It only reads and writes the iCloud Drive folder described above.

The dot at the top goes green when it's ready. The switch in the top right picks how you talk to it:

- **Hold Option:** hold right Option, talk, let go.
- **Hey Jev:** always listening. Say "Hey Jev, open Spotify" in one go, or say "Hey Jev", wait for her reply, then give the command.



### Or let Claude Code set it up

Paste this into Claude Code with the repo link:

> Clone [https://github.com/henryklunaris/hey-jev](https://github.com/henryklunaris/hey-jev) and set it up on my Mac. Check Python 3 is installed and help me install it if not. Create a venv from requirements.txt, build the app with `python setup.py py2app -A`, then tell me which API keys I need, where to get them, and which macOS permissions to grant. Then open the app from the dist folder.

Use Claude Code (the terminal, or the Code tab in the desktop app). The chat side of Claude Desktop runs commands in a Linux sandbox, not on your Mac, so the Mac only packages fail there.

## Using the window

- **Minimise** with the yellow button or Cmd+M.
- **Resize** from any edge. It opens a bit smaller than it used to, centered, and it will not go under about 640 by 420, so the sidebar and the stat cards still fit. Home card values shrink and the captions wrap onto a second line instead of ending in an ellipsis. Pages scroll instead of cutting off when the window is short. The size and position are remembered the next time it opens. A saved frame that is off the screen, or still sitting in the bottom-left corner at the default size, is centered again.
- **Close** hides the window but keeps it listening. Click the Dock icon to bring it back.
- **Mini bar.** Minimizing or closing the window shows a small bar at the bottom of the screen. It is on by default; turn it off in Settings. Type a command and press Return, or hold the mic button the same way you hold right Option. She speaks the reply, and it shows in the bar for a moment. Return does not open this window again. The + button does. Esc, or Window > Hide Mini Bar, hides the bar until you open this window and hide it again. Quitting the app hides the bar and leaves it hidden. A typed line is handled the same way as something she heard: local commands stay local, and anything else goes to TypeSafe or the LLM. My Love is still spoken with the Mac say command. Drag the pill from its background or its edges. The + button, the text field, and the mic still take their own clicks. It stays on top, on every Space and over full-screen apps, and it remembers where you left it, including on another display. A saved spot that misses every screen is put back at the bottom center.
- **Check for updates.** Settings, or Hey Jev > Check for Updates…, asks GitHub once whether henryklunaris/hey-jev main has commits this fork's main does not. It shows that you are up to date, or the short sha, date, and first line of each new commit, and it can open the compare page in the browser. It does not download, install, or apply anything. There is no background check.
- **Keep on Top** in the Window menu (Cmd+T) keeps it above other apps. Off by default.
- **Quit** with Cmd+Q.



## Running from the terminal

Useful for seeing the Jev trace (every question, answer and confidence per turn):

```bash
.venv/bin/python siri.py               # hold right Option mode, trace prints to the terminal
.venv/bin/python siri.py --wake        # Hey Jev mode, always listening
.venv/bin/python siri.py --text "open spotify and turn it down"   # one turn, no mic
.venv/bin/python siri.py --text "what time is it"
.venv/bin/python siri.py --text "open cap cut"
.venv/bin/python siri.py --text "what's my schedule today"
.venv/bin/python siri.py --text "what's the weather"
.venv/bin/python siri.py --text "what's today"
.venv/bin/python siri.py --text "when's my next meeting"
.venv/bin/python siri.py --text "what's on my calendar"
.venv/bin/python siri.py --text "brief me"
.venv/bin/python siri.py --text "check my messages from My Love"
.venv/bin/python siri.py --text "take a note: buy oat milk"
.venv/bin/python siri.py --text "what's due this week"
.venv/bin/python siri.py --text "start focus mode for 25 minutes"
.venv/bin/python siri.py --text "log IHSS hours: 4 hours today"
.venv/bin/python siri.py --text "check my case status"
.venv/bin/python siri.py --text "what's Zoe got tomorrow"
.venv/bin/python siri.py --text "what can you do"
.venv/bin/python siri.py --text "am I working this weekend"
.venv/bin/python siri.py --text "how long until payday"
.venv/bin/python siri.py --text "open settings"
.venv/bin/python siri.py --bridge-secret
.venv/bin/python siri.py --ui          # same as the app, but shows as "Python" in the Dock
```

"Check my messages from My Love" speaks with `say` and needs Full Disk Access on whichever app you run it from. "Check my case status" opens a browser. "Start focus mode" turns focus on; the off shortcut only runs if Hey Jev stays open, so a one-shot `--text` run will not turn it off. `--bridge-secret` prints a new Keychain secret. The trace for the local phrases above should not show a Jev or Haiku call.

Keys can also go in a `.env` file in this folder (`TYPESAFE_API_KEY`, `FISH_AUDIO_API_KEY`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`). A key in `.env` takes priority over the one saved in the Keychain. The bridge secret is the exception: `JEV_BRIDGE_SECRET` is read from the Keychain only, not from `.env`.

## How it works

1. Audio is recorded while you hold right Option. In Hey Jev mode the mic stays open, and each phrase is transcribed locally and only acted on if it starts with "Hey Jev".
2. faster-whisper transcribes it locally for free, about 0.8s.
3. Local commands (weather, today, calendar, the brief, messages, notes, due, focus, IHSS, case status, Zoe, time, date, open apps, and a named Jev shortcut) are chosen in `decide()` from the transcript alone, before any TypeSafe or LLM call. Anything else is one Jev call that asks every question at once (category, is it compound, target, which app, which action, volume level, and so on). The code ignores the answers that don't apply. This is the speculative fan-out pattern from the TypeSafe docs.
4. If Jev says the request is two things, a second Jev call asks the same questions twice, scoped to "the first action" and "the second action". No LLM needed to split.
5. The action runs as a one line `osascript` or shell command. Opening an app uses `open -a`. Quitting uses a polite terminate, not AppleScript. Spoken text is never pasted into an AppleScript string.
6. A scripted reply with emotion tags is picked at random and played. Fixed lines are pre-rendered into `cache/tts/` on first launch, so replies are instant. `{app}` is filled from `apps.json`, using the `say` name when one is set. The time, a calendar title, and any other app name are generated when you ask. LLM answers are generated live too.

Below 0.65 confidence it asks you to say it again, twice in a row and it gives up.

## What it costs

- **Fish Audio:** $0. The `s2.1-pro-free` model string on the API is free until the end of November 2026. You don't need to top up API credits. (Their MCP and web playground bill your plan credits instead, this app doesn't use those.) After November the paid `s2.1-pro` is $15 per million characters, and the cached replies mean a normal day of use is a few cents.
- **Jev:** $0.042 per million input tokens, output free. One command is about $0.00004, a two part command about $0.00011.
- **Whisper:** free, runs on your Mac.
- **OpenRouter:** Claude Haiku for questions, about $0.0002 per answer. Dictation, if you use it, also goes through OpenRouter unless an OpenAI key is saved.



## Troubleshooting

- **Holding Option does nothing.** The app needs Accessibility access. Add it under System Settings > Privacy & Security > Accessibility, then quit and reopen it.
- **"401 Unauthorized" in the window.** One of your keys is wrong or expired. Re-paste it in the Keys tab. If you also have a `.env`, check the key there, because it wins over the Keychain.
- **The app won't open again.** It's probably still running with the window closed. Click its Dock icon, or quit it properly with Cmd+Q and open it again.
- **Checking what happened.** Every phrase it heard, what Jev decided and what she said is logged to `~/Library/Logs/Hey Jev.log`.
- **It stopped controlling apps after a macOS update.** Updates can reset permissions. Check Microphone, Accessibility, Automation, and Calendars under Privacy & Security again.
- **Calendar says it doesn't have access.** System Settings > Privacy & Security > Calendars, set Hey Jev to Full Access, then ask again. Write-only access is not enough. If you asked from `python siri.py --text`, the grant is on Terminal or Cursor, not on the app bundle.
- **Messages says to turn on Full Disk Access.** That command is the only one that needs it. Add Hey Jev (or Terminal / Cursor, if you used `--text`) under Privacy & Security > Full Disk Access, then ask again. Leave it off and the rest of the app still works.
- **The iPhone shortcut never speaks a reply.** Hey Jev has to be running on the Mac. The JSON file has to land in `iCloud Drive/Jev/inbox`, the signature has to be the HMAC of `cmd|ts|nonce`, and the phone's clock has to be within 2 minutes of the Mac. A reused nonce is ignored. A reply file older than 10 minutes is deleted on the Mac.



## Files

- `siri.py` all the logic: questions, actions, replies, Whisper, Fish, LLM fallback
- `commands/` local commands, split by area. `commands/config.py` holds the maps you edit (`KNOWN_APPS`, `APP_NICKNAMES`, `SITE_CONFIG`, `SHIFT_TITLE_PATTERNS`, `HOME_ADDRESS`, `BREA_STORE_ADDRESS`, `LEAVE_BUFFER_MINUTES`, `LEAVE_TYPICAL_DRIVE_MINUTES`, `MY_LOVE_HANDLES`, `PRINCESS_ACADEMY_URL`, `SHOPIFY_ORDERS_URL`). The other modules cover time and date, calendar and shifts, the local shift override, the MapKit drive, money, notes and the due list, messages, media, Mac controls, the Matrix rain in Terminal, the verified Jev shortcuts folder, yes/no confirmation, and the iPhone bridge. `import commands` is unchanged, so `siri.py` and the alias build keep the same entry points.
- `tests/` routing tests, the shortcut-folder safety check, and iPhone bridge validation. They mock `shortcuts` and `osascript`, so they run without macOS: `python3 -m unittest discover -s tests` or `python3 -m pytest`. GitHub Actions runs pytest on Python 3.9 and 3.12 for every push and pull request. The workflow does not install `requirements.txt`, because those packages include macOS-only builds and the tests do not import them.
- `apps.json` the apps Jev can open, quit, hide, minimise, or focus by name. Other installed apps still open and quit from the transcript.
- `dictation.py` and `bubble.py` dictation and its waveform bubble, `vocabulary.example.json` its word fixes (copy to `vocabulary.json`)
- `assistant_ui.py` the window: status, mode switch, and the Home (stats), Dictionary, Apps, Dictation history, Privacy, Settings (microphone and the mini bar switch) and Keys tabs. `assistant_layout.py` is the size math for that window (default, minimum, and where each control sits when you resize). `mini_bar.py` decides when the floating command bar is shown, where a drag leaves it, and how a typed line is queued. It does not import AppKit. `updates.py` is the on-click read of `api.github.com` for upstream commits. It does not import AppKit, and it does not download code.
- `secrets_store.py` Keychain read / write
- `app.py` and `setup.py` the app bundle entry point and the py2app config, output lands in `dist/`
- `assets/` the app icon



## Change the voice

`VOICE_ID` at the top of `siri.py`. Find voices at [https://fish.audio/?fpr=henryk](https://fish.audio/?fpr=henryk) open one and copy its ID from the page link. Her replies re-render in the new voice automatically on the next launch.