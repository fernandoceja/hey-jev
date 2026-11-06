# Eney-style bubble v2: plan

Status: **plan only, waiting for Fernando's approval.** No build PR starts until this PR is approved.

Builds on PRs #76–#81 (original orb, drag placement and edge snap, click popover, chips and history, polish, full window). Nothing is restarted. The public API in `orb_view.make_orb_view()` and the placement rules in `mini_bar.py` stay, and the new behavior layers on top of them.

Planner's note: the first draft was written in a cloud session that couldn't run REA. Fernando then ran **PR 0** on the Mac (notes in `docs/plans/eney-bubble-v2-rea-notes.md`). REA `analyze` returned `provider_unavailable` because no disassembler is installed, so those notes come from reading Eney's resource folder and file names. This revision folds them in:
- the three-layer motion model (passives, accents, state clip)
- idle accents every 4–9 s
- `lookIntensity` for each state
- eye-shape emotions
- one-shot reactions

Clip frame counts are converted at an **assumed 60 fps** (unconfirmed). Every number is a named constant, so it's easy to retune. Eney's assets and code are never copied: Jev's art stays original 2D Core Animation layers in Jev's own palette, with no USD and no 3D.

---

## Executive summary

1. **Rendering moves from a 30 fps `drawRect_` timer to a Core Animation layer tree.** Idle motion then runs in the window server, with no Python per frame, and idle CPU drops to under 1%.
2. **All motion math goes in one pure module, `orb_motion.py`.** It holds the spring solver, pupils, stretch, docking, the capture zone, the menu and the expand geometry, all tested headless on Ubuntu CI the way `tests/test_orb.py` already works.
3. **The work is 14 small PRs in order:** render, idle character (passives and accents), press/drag, peek-dock, capture zone, action menu, mark up, expand, window content, state machine and voice, reactions, then optional features. Each one has a paste-ready Haiku 5.5 prompt with the hard rules copied in.

## Decisions (answered by Fernando, Oct 30 2026)

| # | Decision | Answer | What the plan does |
|---|---|---|---|
| R1 | Body color | **Agreed:** keep Jev's cyan-to-indigo | One `ORB_PALETTE` token in `orb_motion.py` |
| R2 | Single click on the idle orb | **Agreed:** it opens the full window | PR 6a. The quick popover moves to right-click and stays on ⌃⌥J. |
| R3 | When the action menu appears | **Changed:** on **any drop** (a real drag, not a click), anywhere on screen. The capture zone is separate. | PR 5a shows the menu after every drop that isn't on the capture zone. A drop on the capture zone takes an area capture and opens the **existing** post-capture choice panel (PR 4). |
| R4 | Tuck into the edge | **Agreed:** on by default, with a toggle | PR 3b, pref `orb_peek_dock` |
| R5 | Blink | **Changed:** keep it, as a **random idle accent** (the notes show `idle_random_blink` clips) | PR 2 accent scheduler, every 4–9 s |

### Still open: what the drop menu acts on (confirm when you review PR 5a)
On an ordinary drop there's no picture yet. My recommendation:
- **Ask**, **Copy Image** and **Find Image** each start the existing area capture (`screencapture -i`, crosshair), then run the existing handler on that file.
- **Mark up** opens the drawing overlay directly.

If you'd rather capture the window under the drop point automatically, it's a one-line swap to `screenshot_command("window")`.

---

## 1. Gap analysis

| # | Eney behavior | Jev today (code) | Gap | Closed by |
|---|---|---|---|---|
| 1 | Glossy 3D sphere, fixed specular highlight, translucent edges, soft shadow, matte white eyes with pupils | `orb_view.JevOrbView.drawRect_`: radial `NSGradient`, gloss oval that moves with the bob, window shadow, rounded-rect eyes, **no pupils** | Not layered, the highlight moves with the body, no drawn shadow, no eyeballs or pupils | PR 1 |
| 2 | Rests just off the left edge and slides in with a spring when the cursor nears | `mini_bar.snap_origin` snaps to a 12 pt inset inside the visible frame (`ORB_EDGE_INSET`, `ORB_SNAP_BAND`) | No off-edge rest, no hot zone, no spring | PR 3b |
| 3 | Slow 2–3 s bob, fixed highlight, pupils track the cursor. Per PR 0: always-on breath and float, plus a random accent every 4–9 s (blinks, look-around, yawn, bounce, wave and others). | `orb_pose`: 1.5 pt bob over 4 s and a **fixed** blink every 7 s, redrawn by an `NSTimer` at 1/30 s (`OrbTicker`) | The bob is too slow and small, there's no breath or float layer, the blink isn't random, there are no other accents and no cursor tracking, and it costs CPU | PR 2 |
| 4 | Press squash about 0.1 s, eyes squash too | None. The drag loop in `MiniBarBackground._collapsed_click_or_drag` only moves the frame. | Missing | PR 3a |
| 5 | Drag stretches with velocity and lags like a stiff spring | The window origin follows the cursor exactly (`drag_origin`). | No physics | PR 3a |
| 6 | Edge capture zone panel ("Drag to capture · Esc to cancel") | None. Screenshots exist via `commands/captures.screenshot_command("area")`, which is `screencapture -i`. | No zone UI and no drag trigger | PR 4 |
| 7 | Drop **anywhere** (R3): jiggle, then a vertical menu (Ask, Copy Image, Find Image, Mark up). Hover lightens, a click closes it instantly, Mark up gives a crosshair for drawing. | `finish_drag` snaps with no jiggle. A post-capture choice panel exists (`capture_choice_actions`: `ask_jev`, `share_copy`, `ask_google` for Lens, and more). | No jiggle, no fan-out menu on drop, no Mark up overlay | PR 3a, 5a, 5b |
| 8 | Click: the window grows out of the bubble (10% → 100%, about 0.3 s spring), and the bubble docks on the sidebar/chat divider. Sidebar has Get started, + New chat and categories. Chat has a greeting, a pill input with mic, and chips. | `expandMiniBar_` opens the popover, and the popover's expand button calls `_show_full_window`, which uses `makeKeyAndOrderFront_` with no animation. `full_window.full_layout` has `SIDEBAR_W = 200` and a history list. | No grow animation, no docking, and the sidebar and chat content differ | PR 6a, 6b |
| 9 | Collapse is the exact reverse | Closing the full window just hands back to the orb (`windowWillClose_`). | No animation, no undock | PR 6a |
| 10 | Listening, thinking/working (spinner), speaking. Eyes carry the emotion, motion stays low. Per PR 0, the states are idle, thinking (eyes stop tracking), searching, voiceInput, readingAloud and still, each with its own clips and `lookIntensity`. | `orb_state()` maps statuses to 5 states. The listening ring and mic glyph, thinking ellipsis, speaking mouth and error "!" are already accessible shape cues. | No state machine, no per-state look intensity, no eye shapes, no spinner, and the mouth doesn't follow Fish audio | PR 7 |
| 11 | One-shot **reactions** (PR 0): success, failure, getReady, dizzy after a rough drag, heart eyes, low disk space, and others | None | Reaction queue, eye-shape emotions, triggers | PR 7b |
| F1 | Local-first routing | **Already have it**: `commands/model_router.py`, `router_shadow`, and `fm serve` on 127.0.0.1:1976 | None. Reuse it. | n/a |
| F2 | Proactive suggestion: translate after copy | `commands/clipboard_history.py` exists and doesn't suggest anything | Suggest-only chip | PR 8b |
| F3 | Start my day / Plan my day / Morning brief | The `plan_day` chip already exists, using the phrase "brief me" | Only a "Start my day" alias and chip | PR 8c |
| F4 | Downloads/Desktop tidy that asks first | None | A **scan-only** proposal list. Moving files needs your later approval. | PR 8d |
| F5 | Wand: shake the mouse, then point | None | Shake detection, then point, then Ask | PR 8e |
| F6 | @-mention search for files and apps | `commands/apps.py` and the app aliases exist | `@` picker using local `mdfind` and the apps list | PR 8a |

---

## 2. Architecture

### New modules

- **`orb_motion.py`** is pure Python and never imports AppKit, the same pattern as `mini_bar.py` and `full_window.py`. Every number in section 3 lives here as a named constant. It provides:
  - `spring(t, x0, x1, stiffness, damping, mass=1.0, v0=0.0) -> (x, v)`: a closed-form damped harmonic oscillator covering the under-, critically- and over-damped cases.
  - `spring_done(x, v, x1, eps=0.25)`
  - `pupil_offset(eye_center, cursor, max_offset=3.0, reach=300.0)`
  - `drag_stretch(vx, vy) -> (sx, sy, angle)`
  - `follow_step(pos, vel, target, dt, stiffness, damping)`
  - `peek_frame(...)`, `peek_edge_allowed(...)` and `in_hot_zone(...)`
  - `capture_zone_state(prev_shown, cursor, velocity, screen)` with hysteresis
  - `menu_layout(orb_frame, screen, n)`, which reuses `mini_bar.popover_side`
  - `expand_rects(orb_frame, target_frame)`, `dock_point(window_frame)` and `voice_pose(state, t, level)`
  - `wav_envelope(path, hz=30)`, using stdlib `wave` and `audioop`-free RMS math (so it also works on 3.12)
  - `shake_detected(samples)`
- **`orb_character.py`** is pure Python too, and holds the PR 0 character model: states, the clip table, the accent scheduler, the reaction queue and the eye-shape library (see "Character model" below). It's added in PR 2 and grown in PRs 7 and 7b.
- **`orb_layers.py`** is AppKit/Quartz only and is loaded lazily, like `make_orb_view`. It builds the layer tree and the `CABasicAnimation`/`CASpringAnimation` objects from the constants in `orb_motion`. Tests never import it.
- **`capture_zone.py`** (pure geometry and copy) and **`markup.py`** (pure stroke model: add, undo, clear, bounds) are added in PRs 4 and 5b.

### Layer tree

The tree is inside `JevOrbView`, which is layer-backed with `wantsLayer = True` and `layerContentsRedrawPolicy = never`. Order is back to front:

1. `shadowLayer`: an ellipse `shadowPath` 44×10 pt at the bottom, `shadowRadius 8`, `shadowOpacity 0.35`, black. The window's own `setHasShadow_` is turned **off** so there aren't two shadows.
2. `bodyGroup`: the parent of everything that bobs and squashes.
   1. `bodyLayer`: a 56 pt circle. Its `contents` is a CGImage pre-rendered **once per backing scale and palette** (radial gradient, darker lower shade, edges at 85% alpha so they read as translucent). It's re-rendered only on `viewDidChangeBackingProperties` or an appearance or palette change.
   2. `eyeL` and `eyeR`: 11 pt eyes with a matte white radial gradient (#FFFFFF to #E4E6EE), no gloss. Each eye is masked by a `CAShapeLayer` whose `path` comes from the eye-shape library, so blinks and emotions are path morphs.
   3. `pupilL` and `pupilR`: 4.4 pt black circles, children of the eyes, clipped by the eye mask. They're hidden for shapes with no pupil, such as closed, smile-closed and heart.
   4. `glyphLayer`: a `CAShapeLayer` for the existing state cues (mic, ellipsis, mouth, "!") and the PR 7 spinner arc.
3. `highlightLayer`: a sibling of `bodyGroup`, **not** a child, so it doesn't bob. It's a soft white ellipse (about 20×12 pt) at the upper left, alpha 0.85, sized so it stays inside the body through the whole ±2.5 pt bob.

### Character model (from the PR 0 study notes)

Jev copies Eney's **structure**, not its assets. Motion has three layers that add together, plus one-shot reactions on top. Frame counts from the notes are converted at an assumed 60 fps.

**Layer 1: always-on passives** (only while idle, and paused in `still`)
- **Float:** the 2.6 s ±2.5 pt bob observed in the video, plus a very slow x drift of ±1.0 pt over 25 s (the `floating` clip is about 1,500 frames).
- **Breath:** `bodyGroup` scale y 1.0 to 1.015 and scale x 1.0 to 0.995. The base cycle is 7.5 s (about 450 frames), divided by a random speed from 0.5 to 1.3, so each cycle lasts 5.8 to 15 s. A new speed is picked each cycle, at a breath trough.
- Both are infinite `CABasicAnimation`s, so they cost nothing in Python.

**Layer 2: idle accents.** One single-shot NSTimer, rescheduled at a random **4–9 s** delay. It fires only in `idle`, never during a drag, menu, popover or reaction, and with Reduce Motion off. Each firing picks one weighted accent and never repeats the previous one. Each accent is a `CAAnimationGroup` built from the table:

| Accent | Frames → s | Weight | What moves | lookIntensity during |
|---|---|---|---|---|
| `blink` | 20 → 0.33 | 30 | Both eyes: open → closedDown → open | 1.0 |
| `blink_stagger` | 28 → 0.47 | 15 | Left eye, then the right eye after 0.08 s | 1.0 |
| `double_blink` | 2 × 20 → 0.7 | 10 | Two blinks | 1.0 |
| `look_around` | 90 → 1.5 | 12 | Pupils sweep left, right, then center, overriding the cursor | 0.0 |
| `yawn` | 1.6 s | 6 | Eyes go closedUp, the mouth opens 6 pt, scale y 1.06 | 0.0 |
| `bounce` | 0.6 s | 8 | y hop of 6 pt with a squash on landing (k=500, c=18) | 0.5 |
| `wave` | 1.2 s | 5 | A small original "hand" nub on a 0.2 s ±20° rotation | 0.5 |
| `happy` | 1.0 s | 8 | Eyes go smileClosed | 0.0 |
| `jiggle` | 0.5 s | 4 | A ±4% scale wobble (k=500, c=14) | 1.0 |
| `balance_eyes` | 1.4 s | 2 | Pupils tilt together left, then right, with ±4° body rotation | 0.2 |

**Layer 3: one clip per state.** `orb_character.resolve(status, held, reduce_motion, menu_open)` returns the state. The clip under each state sets `lookIntensity`, which multiplies `pupil_offset`. It eases between values over 0.25 s.

| Character state | From Jev status (`orb_state`) | Clips | Switch | lookIntensity |
|---|---|---|---|---|
| `idle` | Ready or idle | passives plus accents | accents every 4–9 s | 1.0 |
| `listening` (voiceInput) | right Option held, Listening, Dictating | `listen_1`–`listen_3` (wide eyes, a level-driven body pulse, a slight lean) | every 3 s | 0.6 |
| `thinking` | Transcribing, Thinking, Finishing | `think_1`–`think_3` (eyes up-right with a spinner, half-closed sceptic eyes, a slow look-up) | every **7 s** | **0.0** |
| `searching` | Doing it | `search_1`–`search_2` (a pupil scan sweep, plus the spinner) | every 4 s | 0.3 |
| `speaking` (readingAloud) | Speaking | `talk_1`–`talk_4` (the mouth follows the WAV envelope, with small eye squints on peaks) | random **2–4 s** | 0.5 |
| `still` | Reduce Motion, or the screens asleep | a static pose with the current eye shape | — | 0.0 (pupils centered) |

**Eye-shape library.** `eye_shape(name, size)` returns pure Python Bézier control points that `orb_layers` turns into a `CGPath`. Every shape has the **same number of points**, so `CABasicAnimation` on `path` morphs cleanly.
- The shapes are `open`, `closedDown`, `closedUp`, `smileClosed`, `happy`, `sad`, `sceptic`, `heart`, `wide` and `spiral` (for dizzy).
- Body emotions use the existing squash and a `Scale_Y` channel on `bodyGroup`.
- All shapes are drawn fresh for Jev.

**Reactions.** These are one-shot and play over any state except `still`. The queue holds at most one pending reaction, the newer one wins when the priority is equal, and each reaction has a cooldown.

| Reaction | Trigger in Jev | Eyes / body | Duration | Priority | Cooldown |
|---|---|---|---|---|---|
| `get_ready` | Right Option goes down, or the wake word is heard (before listening) | Bounce of 4 pt, eyes `wide` | 0.35 s | 3 | 0 |
| `success` | A command ends on Ready after a real reply (not an idle "ready" line) | Spin hop: z-rotation 360° plus a 6 pt hop, eyes `smileClosed` | 0.8 s | 2 | 20 s |
| `failure` | Something went wrong / Time's up | Eyes `sad`, then `sceptic`, a droop (scale y 0.94), and the "!" glyph stays. Replaces the plain error pose. | 1.0 s | 3 | 5 s |
| `dizzy` | On a drop, if the drag had 6 or more direction reversals, or spent 0.5 s or more above 3,500 pt/s | Eyes `spiral`, a ±6° wobble | 1.2 s | 2 | 10 s |
| `heart` | A turn that thanks Jev ("thanks", "thank you", "love you, Jev"), matched by pure text | Eyes `heart`, a 1.08 scale pulse | 1.0 s | 1 | 60 s |
| `low_disk` | `shutil.disk_usage("/")` checked at launch and then at most hourly reports free space under 10 GB or 5% | Worried `sad` eyes and a small original sweat-drop glyph. Also highlights the **Mac health** chip, which still runs the scan only. | 1.5 s, then once per hour at most | 1 | 3600 s |
| `wave` | The first time the orb is shown after launch | The wave accent | 1.2 s | 1 | once per launch |

None of these add listening sockets, network calls or permissions. The disk check is local stdlib.

### Why not SceneKit or Metal

PR 0 shows that Eney ships a 77 MB USD model with baked clips. Jev deliberately doesn't. A 72 pt sprite with one highlight and morphing eye paths is exactly what layers are for. SceneKit or Metal would add a GPU context, launch cost, and a py2app packaging risk, for no visible gain. Revisit only if PR 1's hand test shows the gradient sprite can't sell the 3D look.

### Timers and CPU

| What | Mechanism | Runs when |
|---|---|---|
| Idle bob, breath, float drift and shadow pulse | `CABasicAnimation` with repeatCount=∞, in the render server | The orb is visible, not docked in the window, and Reduce Motion is off |
| Idle accents | One **single-shot** `NSTimer`, rescheduled at a random 4–9 s (about 10 wakeups a minute, each building one `CAAnimationGroup`) | The same as above, and only in `idle` |
| State clip switching (7 s thinking, 2–4 s speaking, and so on) and reactions | Single-shot `NSTimer`s, each invalidated when the state changes | Only in that state |
| Pupil tracking | One `NSTimer` at **20 Hz** reading `NSEvent.mouseLocation()`. It exits early if the cursor moved less than 0.5 pt. | The orb is visible and the screens are awake (`NSWorkspaceScreensDidSleepNotification` / `DidWake`) |
| Window springs (peek slide, drag lag, jiggle drift, dock move) | A 60 Hz `NSTimer` stepping `orb_motion.spring`/`follow_step`, invalidated when `spring_done` | Only during a transition, normally under 0.5 s |
| Expand and collapse | `CASpringAnimation` on a ghost layer | 0.3 s |

There are no global event monitors, no new permissions and no sockets. The existing `OrbTicker` pattern (one timer, invalidated on hide or quit) is reused for both timers.
**Budget:** under 1% CPU for Jev in Activity Monitor with the orb idle, and 0 wakeups from Jev while the screen is asleep.

### Window levels and z-order

| Window | Level | Ordering |
|---|---|---|
| Orb panel (`mini_panel`) | `BAR_LEVEL = 28` (existing) | Front |
| Capture zone panel | `BAR_LEVEL` | `orderWindow_relativeTo_(NSWindowBelow, orb)` |
| Action menu panel | `BAR_LEVEL` | Above the orb |
| Expand ghost panel | `BAR_LEVEL` | Below the orb, removed after the hand-off |
| Full window | `NORMAL = 0` (existing) | Normal |
| Docked orb | A **child window** of `full_window` (`addChildWindow_ordered_(orb, NSWindowAbove)`), so it follows the parent's level, Spaces and minimizing | Removed from the child list and set back to `BAR_LEVEL` on collapse |
| Mark up overlay (one per screen) | 101 (`NSPopUpMenuWindowLevel`), with `fullScreenAuxiliary` collection behavior | Front until Esc or Return |

---

## 3. Animation spec

Springs are written as k = stiffness, c = damping, m = mass (always 1). ζ = c / (2√(k·m)), and overshoot ≈ exp(−πζ/√(1−ζ²)). Everything respects `accessibilityDisplayShouldReduceMotion` (in the "RM" column) and Reduce Transparency, which swaps in solid fills as `orb_view` already does.

| State | Trigger | Transform | Duration | Easing / spring | Level / z | RM fallback |
|---|---|---|---|---|---|---|
| Idle bob | Orb visible and idle | `bodyGroup.position.y` ±2.5 pt. `shadowLayer.transform.scale` 1.0 ↔ 0.94 and opacity 0.35 ↔ 0.28, in phase. Highlight fixed. | 2.6 s period (1.3 s autoreverse) | `easeInEaseOut` (sine-like) | Orb panel | Static |
| Breath and float drift | Orb visible and idle | Breath: scale y 1.0 ↔ 1.015, scale x 1.0 ↔ 0.995. Float: x ±1.0 pt. | Breath 7.5 s ÷ random speed 0.5–1.3. Float 25 s. | `easeInEaseOut` | — | Static |
| Idle accent | Random timer every 4–9 s, idle only | One accent from the Character model table (blink, blink_stagger, look_around, yawn, bounce and others) | Per the table | Per the table (bounce and jiggle use springs) | — | None |
| Pupils | Cursor moves (20 Hz poll) | Pupil offset up to 3.0 pt toward the cursor, × min(1, dist/300) **× lookIntensity** for the current state, clip or reaction | Implicit 0.08 s. lookIntensity changes ease over 0.25 s. | Linear | — | Pupils centered and static |
| Peek rest | Orb snapped to an edge that **has no neighboring display**, and `orb_peek_dock` on | Window x such that 70% of `ORB_PANEL` is past the edge (about 50 of 72 pt) | — | — | Orb panel | Same rest |
| Peek slide-in | Cursor within 24 pt of that edge and within ±100 pt of the orb's center y | Window x to the 12 pt inset | About 0.4 s | k=300, c=22 (ζ≈0.64, about 8% overshoot) | Orb panel | 0.15 s fade-in at the inset position |
| Peek slide-out | Cursor outside the hot zone **and** more than 120 pt from the orb for 1.5 s, with no popover, menu or drag open | Back to the rest x | About 0.45 s | k=200, c=26 (ζ≈0.92, no overshoot) | — | 0.15 s fade |
| Press | `mouseDown` on the idle orb | `bodyGroup` scale (1.12, 0.88), eyes included because they're children | 0.10 s | `easeOut` | — | None |
| Release (click) | `mouseUp` without moving | Scale to (1, 1) | About 0.35 s | CASpring k=500, c=26 (ζ≈0.58, about 10%) | — | None |
| Drag | The drag passes the existing `capsule_click_moved` threshold (4 pt) | The window origin **follows** the cursor target via `follow_step` (k=400, c=36, ζ≈0.9, lag about 50 ms). `bodyGroup` stretches with sx = 1 + min(0.22, speed/3000) and sy = 1/sx, rotated by atan2(vy, vx) (transform = R(θ)·S·R(−θ)). Speed is smoothed with the existing `mini_bar.smooth(a=0.4)`. | While dragging | Per-frame | Orb panel | Window follows exactly with no stretch (today's behavior) |
| Drop | `mouseUp` after a drag (past the 4 pt click threshold) and not on the capture zone | Stretch goes to (1, 1) with a jiggle. Then the existing `finish_drag` snap target is reached with spring k=300, c=24. Then the **action menu opens** (R3), and `dizzy` plays first if the drag was rough. | About 0.5 s | CASpring k=500, c=18 (ζ≈0.40, about 25%, two visible wobbles) | — | Instant snap, then the menu |
| Capture zone in | While dragging: cursor ≤ 4 pt from an **outer** screen edge, or moving toward it faster than 1500 pt/s within 40 pt | A 260×56 panel slides in from that edge, centered on the cursor's y (or x for the top or bottom edge), and is clamped to the visible frame | 0.22 s | k=500, c=40 (ζ≈0.89) | `BAR_LEVEL`, below the orb | Fade 0.12 s |
| Capture zone out | Cursor more than 80 pt from the edge (hysteresis), Esc, or a drop elsewhere | Reverse slide | 0.18 s | `easeIn` | — | Fade |
| Capture drop | Drop while the zone is shown | The orb springs back to its pre-drag origin (k=300, c=24), the zone hides, then `take_screenshot(mode="area")`, which is `screencapture -i`. Esc there cancels natively. When it's saved, the **existing post-capture choice panel** opens. The action menu does **not** open. | — | — | — | Same with no spring |
| Action menu open | Any drop that isn't on the capture zone (R3). Never after a click. | 4 round 40 pt buttons in a column, with 10 pt gaps and labels to the right, on a 14 pt-radius dark material panel (`NSVisualEffectView`, HUD material, dark appearance). Each button goes from scale 0.6 / alpha 0 at the orb's center to its slot. Staggered 30 ms. | About 0.3 s | k=500, c=30 (ζ≈0.67) | `BAR_LEVEL`, above the orb | Appears instantly |
| Menu hover | `mouseEntered` | Button fill from white 8% to 18% | 0.12 s | `easeOut` | — | Instant |
| Menu close | A click on an action (closes **instantly**, no animation), Esc, a click away, or `CHOICE_SECONDS` (20 s) | `orderOut_` | 0 | — | — | Same |
| Expand | Single click on the idle orb (R2) | A ghost panel holds a `cacheDisplayInRect` snapshot of the laid-out `full_window`. Its layer scale goes 0.1 → 1.0 with the anchor at the orb's center mapped into the target frame, and opacity 0 → 1. Then `full_window.makeKeyAndOrderFront_` and the ghost is removed. In parallel, the orb springs to `dock_point()` and scales to 0.5. | Scale about 0.3 s, fade 0.18 s | Scale CASpring k=400, c=32 (ζ≈0.8, about 1.5%). Fade `easeOut`. | Ghost at `BAR_LEVEL` below the orb. Then the orb becomes a child of the window. | 0.15 s crossfade, orb jumps to the dock |
| Docked | The full window is open | Orb at 0.5 scale, centered on the divider: x = win.x + `SIDEBAR_W` − 18, y = win.top − `TITLEBAR_H` − 18 − 12. Bob **off**, pupils still track. Click = collapse. | — | — | Child of the full window | Same |
| Collapse | Click on the docked orb, ⌘W, or closing the full window | Exact reverse: snapshot, hide the window, ghost scale 1.0 → 0.1 into the orb's undocked origin, opacity → 0. The orb un-children, returns to `BAR_LEVEL`, springs to its saved origin (`ORIGIN_KEY`) at 1.0 scale, and the bob resumes. | About 0.3 s | k=400, c=32 | — | Crossfade |
| Listening | Right Option held, or status Listening/Dictating (`orb_state`). Starts with the `get_ready` reaction. | `wide` eyes (scale y 1.15), pupils grow to 5.2 pt, body scales 1 + 0.04·level (meter `_meter_unit`), and listen clips rotate every 3 s. lookIntensity 0.6. The ring and mic glyph stay. | Implicit 0.12 s | `easeOut` | — | Static wide eyes plus the mic glyph |
| Thinking | Transcribing, Thinking, Finishing | Think clips switch every 7 s, for example pupils at (+1.8, +1.8) looking up and right, or `sceptic` half-closed eyes. A 270° spinner arc (`CAShapeLayer`, 1.5 pt, white 70%) rotates around the body. **lookIntensity 0.** The ellipsis glyph stays. | 1.2 s per turn | Linear, repeating | — | Static arc plus the ellipsis |
| Searching / working | Doing it | Pupils scan left and right over 1.6 s, plus the spinner. lookIntensity 0.3. | Clips switch every 4 s | `easeInEaseOut` | — | Static arc plus the ellipsis |
| Speaking | Status Speaking | The mouth glyph's height follows `wav_envelope` of the Fish WAV at 30 Hz (keyframe animation built once per reply). If the file can't be read, it uses a 3.5 Hz pulse between 2 and 5 pt. Talk clips (squints on peaks) switch every random 2–4 s. lookIntensity 0.5. | Length of the reply | Linear keyframes | — | Static open mouth |
| Reactions | See the Character model reaction table | Eye-shape morph plus a body channel | 0.35–1.5 s | Path morph `easeInEaseOut`, body springs | — | Shape change only, no motion (the eye shape still shows the emotion) |
| Error | Something went wrong / Time's up | The **`failure` reaction** (`sad` then `sceptic` eyes, droop). The "!" glyph stays. | 1.0 s | `easeInEaseOut` | — | Static sad eyes plus "!" |

---

## 4. PRs (in order, each mergeable on its own)

There's one branch per PR, `jev/eney-v2-NN-<slug>`, and each opens as a draft. Every PR must leave `python -m pytest` green on 3.9 and 3.12 (`.github/workflows/tests.yml`). The hand-test checklist always includes the **base checks**:

- Build and run as usual.
- Hold right Option and speak a command. It still works.
- ⌃⌥J still focuses typing.
- Zoe mode still refuses.
- The iPhone bridge is unchanged.
- Activity Monitor shows Jev under 1% CPU after 30 s idle.
- With Reduce Motion on (System Settings › Accessibility › Display, view only, don't change other security settings), nothing animates and the state cues are still visible.

### PR 0: REA study (done, Oct 30 2026)
- Fernando ran it on the Mac, read-only. REA `analyze` failed with `provider_unavailable` because no Ghidra, Hopper or IDA is installed, so the notes come from reading Eney's resource folder and file names.
- The notes are committed as `docs/plans/eney-bubble-v2-rea-notes.md`, and their findings are folded into section 2 (Character model) and section 3.
- No assets were copied.
- Still unconfirmed: the clip frame rate. The plan assumes 60 fps. If a later REA run with a disassembler finds otherwise, rescale the `*_FRAMES` constants in `orb_character.py`.

### PR 1: Layer rendering (static)
- **Files:** `orb_motion.py` (new: constants, `ORB_PALETTE`, `pupil_offset`, `layer_geometry()`), `orb_layers.py` (new), `orb_view.py` (`JevOrbView` becomes layer-backed, `drawRect_` path kept only for the `solid` fallback), `tests/test_orb_motion.py` (new). `tests/test_orb.py` stays green.
- **Acceptance:**
  - The layer tree from section 2 is built.
  - The highlight is a sibling of `bodyGroup`.
  - The body image is rendered once per scale.
  - Pupils are centered.
  - The window `setHasShadow_(False)` and the shadow layer draws instead.
  - Existing glyph cues are drawn in `glyphLayer`.
  - `orb_state`, the accessibility label and `accessibilityPerformPress` are unchanged.
- **Unit tests:**
  - `layer_geometry()` keeps the eyes, pupils and highlight inside the 56 pt body for bob offsets −2.5…+2.5.
  - `pupil_offset` is clamped to ≤ 3.0 pt, is zero at distance 0, points toward the cursor in all 4 quadrants, and stays finite for NaN or inf input.
  - Palette values are 0–1 floats.
  - `orb_motion` imports with no AppKit available.
- **Hand test:**
  - The orb looks glossy and 3D, with the highlight at the upper left.
  - There's one soft shadow, not two.
  - It's sharp on Retina and on an external non-Retina display.
  - Moving the window between displays re-renders it crisply.
  - Light and dark mode both look right.
  - Reduce Transparency turns it solid.

### PR 2: Idle character (passives, random accents, eye tracking)
- **Files:**
  - `orb_motion.py`: bob and breath constants, `idle_active()`, `cursor_moved()`
  - `orb_character.py` (new): the eye-shape library (`open`, `closedDown`, `closedUp`, `smileClosed`, `wide`; the rest come in 7b), the `ACCENTS` table, `next_accent_delay(rng)`, `pick_accent(rng, previous)`, `breath_speed(rng)`, `look_intensity(state, clip)`
  - `orb_layers.py`: bob, breath, float and shadow animations; eye `CAShapeLayer` masks; accent animation groups
  - `orb_view.py`: remove the 30 fps `animateOrb:` redraw; add the 20 Hz cursor poll and a single-shot accent timer, both via `OrbTicker`; sleep and wake observers
  - `assistant_ui.py`: `_sync_orb` passes docked, visible and menu-open only
  - `tests/test_orb_character.py` (new), `tests/test_orb_motion.py`, `tests/test_orb.py` (the fixed 7 s blink is replaced by random blink accents per R5, so update its assertions)
- **Acceptance:**
  - The bob is ±2.5 pt over 2.6 s, and breath and float run in the render server.
  - The highlight doesn't move.
  - The pupils follow the cursor anywhere on any display, × lookIntensity, which is 1.0 in idle and 0 during `look_around`.
  - **One accent every 4–9 s** at random, never the same one twice in a row, and only while idle. Blinks are the most common.
  - Shipped accents: `blink`, `blink_stagger`, `double_blink`, `look_around`, `yawn`, `bounce`, `jiggle`, `happy`. `wave` and `balance_eyes` can wait for 7b.
  - Exactly one poll timer and one accent timer exist. Both are invalidated when the orb is hidden, the screens sleep, Reduce Motion is on or the app quits.
  - No `setNeedsDisplay_` calls happen per frame.
- **Unit tests:**
  - `idle_active(visible, motion, docked, asleep)` truth table, and `cursor_moved(prev, now, eps=0.5)`.
  - With a seeded `random.Random`: 1,000 delays all fall within [4, 9] s, `pick_accent` never repeats the previous accent, accent frequencies are within ±5% of their weights, and `breath_speed` falls within [0.5, 1.3].
  - Every eye shape has the same number of points and stays within the eye bounds.
  - Frame-to-seconds conversion: `blink` is 20 frames = 0.333 s at 60 fps.
  - `look_intensity` values match the Character model table.
  - The `OrbTicker` single-timer test still passes for both timers.
- **Hand test:**
  - It bobs and breathes smoothly.
  - Over two minutes you see random blinks (some staggered), a look-around and a yawn or bounce, never on a fixed beat.
  - The eyes follow the cursor across two displays and pause during a look-around.
  - CPU stays under 1% idle.
  - Lock the screen for a minute, then unlock: it's still tracking and there are no duplicate timers (CPU stays low).

### PR 3a: Press, drag and drop physics
- **Files:** `orb_motion.py` (`spring`, `spring_done`, `follow_step`, `drag_stretch`, and `drag_roughness(samples) -> (reversals, seconds_fast)`, recorded on each drag for the PR 7b `dizzy` reaction), `orb_layers.py` (squash, stretch and jiggle helpers), `assistant_ui.py` (`MiniBarBackground._collapsed_click_or_drag`: target = `drag_origin(...)` and window = `follow_step`; a 60 Hz transition timer; at the end, the existing `_finalize_mini_bar_drag`), `tests/test_orb_motion.py`.
- **Acceptance:**
  - Press squashes over 0.10 s.
  - A click still opens what it opens today, because R2 only changes in PR 6a.
  - The drag lags slightly and stretches along the direction of travel, never more than 1.22×.
  - A drop jiggles, then `finish_drag` snaps.
  - The transition timer stops when the spring settles.
  - Multi-display and negative coordinates still behave as `tests/test_orb.py` expects.
- **Unit tests:**
  - `spring` reaches within 0.25 pt of the target by 0.6 s for each spring in section 3.
  - The overshoot fraction is within ±3% of the formula for ζ < 1.
  - The critically and over-damped branches never overshoot.
  - `follow_step` converges and is stable at dt = 1/30 and 1/120.
  - `drag_stretch(0, 0) == (1, 1, 0)`, sx·sy = 1, and sx ≤ 1.22.
  - All functions stay finite for huge or NaN input.
- **Hand test:**
  - Press and hold squashes, and release springs back.
  - A fast flick stretches and trails behind.
  - Releasing jiggles about twice and then snaps to the edge.
  - Dragging across to the second display works.
  - With Reduce Motion on, the drag follows exactly with no stretch.

### PR 3b: Peek-dock
- **Files:** `orb_motion.py` (`peek_edge_allowed(edge, screen, screens)`, `peek_frame`, `in_hot_zone`, `should_retract`), `mini_bar.py` (`PEEK_PREF_KEY = "orb_peek_dock"` and the rest-origin helper), `assistant_ui.py` (the poll timer from PR 2 also checks the hot zone, slide timers, a menu toggle "Tuck Jev into the edge"), tests.
- **Acceptance:**
  - Snapped to the left or right edge with no neighboring display there, the orb rests 70% off-screen.
  - Approaching the edge slides it in (k=300, c=22).
  - It retracts per section 3.
  - It never peeks on an edge shared with another display.
  - Turning the pref off brings back today's 12 pt snap.
  - It never peeks while the popover, menu, a drag, listening or speaking is active.
  - The saved origin is stored as the inset position, so turning peek off is safe.
- **Unit tests:**
  - Edge-allowed with two side-by-side and two stacked displays.
  - Hot-zone bounds.
  - The retract timer rule.
  - `peek_frame` is ≥ 18 pt visible for any screen.
  - The pref parse follows the `enabled_from_pref` pattern.
- **Hand test:**
  - Tucked left, move the mouse to the left edge near the orb and it slides in with a slight overshoot.
  - Move away and it tucks back after about 1.5 s.
  - With an external monitor on the left, it doesn't tuck on the shared edge.
  - The menu toggle works and is remembered after a relaunch.

### PR 4: Edge capture zone
- **Files:** `capture_zone.py` (new, pure: `zone_state`, `zone_frame`, `ZONE_TEXT = "Drag to capture · Esc to cancel"`, the outer-edge test), `assistant_ui.py` (zone panel: `NSPanel`, nonactivating, `ignoresMouseEvents`, HUD vibrancy plus a 55% black fill, `CAShapeLayer` dashed border with `lineDashPattern [5, 4]`, SF Symbol `camera.viewfinder`, label; slide via spring; Esc during the drag cancels and returns the orb), `tests/test_capture_zone.py`.
- **Acceptance:**
  - The zone appears only during a drag at an outer edge, as in section 3, and hides with hysteresis.
  - A drop on it springs the orb home, then runs the **existing** `commands.captures.take_screenshot(mode="area")`, so the file lands in Captures as today. Then the **existing post-capture choice panel** opens, not the PR 5a drop menu (R3).
  - Esc cancels at either stage.
  - No new permissions are needed beyond the existing Screen Recording prompt flow (`permission_failure` path).
- **Unit tests:**
  - Show at ≤ 4 pt, show on a fast approach inside 40 pt, no flicker between 4 and 80 pt, hide beyond 80 pt.
  - Never shown on an inner shared edge.
  - The frame is clamped inside the visible frame on small and negative-origin screens.
  - The text constant is exact.
- **Hand test:**
  - Drag the orb hard to the right edge and the dashed panel slides out.
  - Pull back and it retracts.
  - Drop on it, the crosshair appears, select an area, the file is in Captures, and the usual capture choices panel appears.
  - Esc mid-drag cancels.
  - The capture still works in a fullscreen app's Space.

### PR 5a: Action menu
- **Files:**
  - `mini_bar.py`: `orb_action_menu()` returns four rows that reuse existing ids: `ask_jev` "Ask", `share_copy` "Copy Image", `ask_google` "Find Image" (Lens page, no upload POST, as today) and `markup` "Mark up". It also adds `menu_on_drop(moved, on_capture_zone)`.
  - `orb_motion.py`: `menu_layout`
  - `assistant_ui.py`: the menu panel, tracking areas for hover, and the existing choice-action dispatch
  - tests
- **Acceptance (R3):**
  - After **any drop that isn't on the capture zone**, once the jiggle and snap settle, the menu fans out on the side `popover_side` picks.
  - A click with no drag never opens it, and a capture-zone drop never opens it.
  - Ask, Copy Image and Find Image first run the existing area capture (`take_screenshot(mode="area")`, crosshair), then pass that file to the same handler the post-capture panel uses. If the capture is cancelled with Esc, nothing happens.
  - Hover lightens a button.
  - A click closes the menu **instantly**, then runs the action.
  - Esc, a click away or 20 s (`CHOICE_SECONDS`) closes it.
  - Peek-dock (PR 3b) waits until the menu closes.
  - Until PR 5b lands, Mark up takes an area capture and opens it in Preview (`open -a Preview`), so no feature is dead.
  - VoiceOver reads each button.
- **Unit tests:**
  - It's exactly four rows, in order, with ids that exist in `capture_choice_actions()` (except `markup`).
  - `menu_on_drop` truth table: a click gives False, a drop gives True, a capture-zone drop gives False.
  - `menu_layout` flips sides near the right edge, stays on-screen, and the stagger delays are 0/30/60/90 ms.
- **Hand test:**
  - Drag the orb to the middle of the screen and drop it: it jiggles, then the menu fans out to the right (or to the left near the right edge).
  - A plain click opens the window, not the menu.
  - Hover feels right.
  - Copy Image: select an area, and it's on the clipboard (paste it into Notes).
  - Find Image opens the Lens page.
  - Ask starts a Jev turn about the picture.
  - Esc closes it.
  - Drop on the capture zone and you get the old capture panel, not this menu.

### PR 5b: Mark up overlay
- **Files:** `markup.py` (new pure stroke model: `begin`, `extend`, `end`, `undo`, `clear`, `bounds`, a point decimation of 1.5 pt), `assistant_ui.py` (one overlay per screen at level 101, `NSCursor.crosshairCursor`, `CAShapeLayer` strokes 3 pt `systemRed`; Return saves a full-screen capture composited with the strokes into Captures via `capture_name`; Esc cancels; ⌘Z undoes), `tests/test_markup.py`.
- **Acceptance:**
  - Mark up from the menu turns the cursor into a crosshair.
  - Drawing works on every display.
  - Esc leaves with no file.
  - Return saves one PNG to Captures and shows the existing saved line.
  - No other app receives clicks while the overlay is up.
  - Nothing is uploaded.
- **Unit tests:** stroke add, undo and clear; decimation; bounds across multiple strokes; an empty save is refused.
- **Hand test:**
  - Draw a circle on screen, ⌘Z removes it, draw again, and Return saves.
  - The file opens in Preview with the stroke.
  - Esc mid-draw leaves no file.

### PR 6a: Expand and collapse, plus the divider dock
- **Files:** `orb_motion.py` (`expand_rects`, `dock_point`, `collapse_target`), `full_window.py` (`DOCK_ORB = 36.0` and `dock_rect(layout)`), `assistant_ui.py` (ghost panel snapshot, `CASpringAnimation`, child-window dock and undock, a single click on the orb → `_show_full_window` per R2, right-click → popover, and `windowWillClose_` runs the collapse), tests.
- **Acceptance:**
  - The window grows out of the orb's exact position in about 0.3 s.
  - The orb docks on the sidebar/chat divider at half size and moves with the window.
  - Clicking the docked orb reverses everything, and the orb returns to its saved spot and bobs.
  - The first open (no snapshot yet) lays the window out off-screen first.
  - The full window's remembered frame (`FULL_AUTOSAVE`) still applies.
  - Minimizing or closing the window collapses cleanly.
  - Right-click and ⌃⌥J still reach the popover and typing.
- **Unit tests:**
  - `expand_rects` start size is 10% of the target, centered on the orb, and stays on-screen.
  - `dock_point` x = win.x + 200 − 18 for several window frames, and the dock never overlaps the titlebar.
  - `collapse_target` returns the saved origin or a `place_bar` fallback after a display is unplugged.
- **Hand test:**
  - Click the orb and the window blooms out of it.
  - The orb sits on the divider, and dragging the window carries it along.
  - Click the orb and everything shrinks back.
  - Repeat ten times quickly and nothing gets stuck.
  - Unplug the external display while the window is open, then collapse: the orb lands on-screen.

### PR 6b: Full window content
- **Files:** `full_window.py` (layout: a "Get started" list, a "+ New chat" button, categories (Today, Captures, Games, Mac), a greeting via `mini_bar.greeting_text`, a pill input of 44 pt height with radius 22 and a mic button, and chips below using `popover_chip_ids`), `assistant_ui.py` (wire the views; + New chat clears `TypedHistory` on screen only), `tests/test_full_window.py`.
- **Acceptance:**
  - The sidebar and chat look as in the video, using Jev's REA palette tokens.
  - The placeholder reads "Ask Jev anything…" until PR 8a, when it becomes "Type @ to search files, apps…", so there's no promise the feature can't keep.
  - Chips run the same `chip_command_plan`.
  - The mic is the same `miniMicDown:` path.
  - History stays reachable under a "Recent" category.
- **Unit tests:**
  - Layout frames are inside bounds at min, default and max sizes, and nothing overlaps.
  - The dock rect stays clear of the sidebar list.
  - The greeting text is right.
  - The chip row drops chips that don't fit rather than clipping them (existing `chip_frames`).
- **Hand test:**
  - Resize from the minimum to the maximum and nothing clips.
  - Each chip works.
  - + New chat clears the view.
  - The mic in the input works.
  - Dark and light mode look right.

### PR 7: State machine and voice states
- **Files:**
  - `orb_character.py`: `resolve(status, held, reduce_motion, menu_open)` returns a character state (`idle`, `listening`, `thinking`, `searching`, `speaking`, `still`); `STATE_CLIPS` with per-clip lookIntensity; `next_clip(state, rng, previous)` and `clip_switch_delay(state, rng)` (7 s thinking, 4 s searching, 3 s listening, random 2–4 s speaking); `sceptic` added to the eye shapes
  - `orb_motion.py`: `voice_pose`, `wav_envelope`
  - `orb_layers.py`: eye, pupil and spinner animations, and clip application
  - `orb_view.py`: `configure` runs `resolve` and applies the clip
  - `siri.py`: **only** a hook that records the path of the Fish WAV about to play, such as a module-level `LAST_REPLY_WAV`. No change to playback, keys or network.
  - tests
- **Acceptance:**
  - Each state looks as in section 3 and the Character model table.
  - **Thinking stops eye tracking** (lookIntensity 0) and switches clips every 7 s.
  - Speaking switches talk clips every 2–4 s, and the mouth follows the actual reply audio.
  - `still` covers Reduce Motion and screens asleep.
  - The existing shape cues (ring, mic, ellipsis, mouth, "!") stay.
  - The spinner runs only in thinking and searching.
  - Idle accents are suspended in every non-idle state.
  - Nothing new runs while idle.
- **Unit tests:**
  - The `resolve` mapping for every status in `orb_state`, plus `held`, Reduce Motion and menu open. Existing `orb_state` tests are unchanged.
  - Clip switch delays with a seeded RNG (thinking exactly 7 s, speaking within [2, 4]); `next_clip` never repeats the previous clip.
  - lookIntensity per state matches the table.
  - `voice_pose` for each state at a few times stays inside the eye and body bounds; listening scales with level, clamped from 0 to 1.
  - `wav_envelope` on a generated 8- and 16-bit mono and stereo WAV (written in `tmp_path`) gives 30 values per second from 0 to 1. A missing or bad file returns `[]`, and the 3.5 Hz pulse fallback is used.
- **Hand test:**
  - Hold right Option: the eyes widen and the body pulses with your voice.
  - Release: the spinner shows while it thinks, and the eyes **stop** following the mouse.
  - Jev speaks: the mouth moves with the words, and the eyes follow the mouse only loosely.
  - Turn Reduce Motion on: the orb holds still with the right eye shape.

### PR 7b: One-shot reactions and eye-shape emotions
- **Files:**
  - `orb_character.py`: the remaining eye shapes (`happy`, `sad`, `heart`, `spiral`); a `REACTIONS` table (trigger, eye keyframes, body channel, duration, priority, cooldown); a `ReactionQueue` (`offer(name, now)`, `current(now)`, `cancel_all()`); `is_thanks(text)`; `rough_drag(reversals, seconds_fast)`; `low_disk(free, total)`; and the `wave` and `balance_eyes` accents
  - `orb_layers.py`: reaction animation groups
  - `orb_view.py` and `assistant_ui.py`: wire the triggers from the table
    - `get_ready` on right Option down or the wake word
    - `success` and `failure` from the status that ends a command (reuse `mini_bar.status_is_final`)
    - `dizzy` on a drop, from PR 3a's `drag_roughness`
    - `heart` from the typed or heard text of the turn
    - `low_disk`, run on a background thread at launch and at most hourly
    - `wave` on the first show
  - `mini_bar.py`: a Mac-health chip highlight flag
  - tests
- **Acceptance:**
  - Each reaction plays as in the Character model table, then returns to the current state's clip.
  - Priorities and cooldowns hold: no reaction spam, and `success` at most once per 20 s.
  - The plain error pose is replaced by `failure`, and "!" stays.
  - `dizzy` plays before the PR 5a drop menu opens.
  - `low_disk` only highlights the Mac health chip, which **still runs the scan only**. Nothing is cleaned or deleted.
  - With Reduce Motion on, reactions change the eye shape only, with no movement.
  - No network, sockets or permissions are added.
- **Unit tests:**
  - `ReactionQueue` priority, replacement and cooldown, using a fake clock.
  - `is_thanks` positives and negatives ("thanks", "thank you Jev", "no thanks to the weather" counts as a negative, and so do empty strings).
  - `rough_drag` thresholds (6 reversals, 0.5 s above 3,500 pt/s).
  - `low_disk` at 10 GB and at 5% (`shutil.disk_usage` is stubbed and never hits the real disk).
  - Every new eye shape has the same point count as `open`.
- **Hand test:**
  - Press right Option: a quick ready-bounce.
  - Ask the time: a happy spin hop.
  - With Wi-Fi off, ask a cloud question: sad, then sceptic eyes, and "!".
  - Shake the orb around wildly and drop it: spiral eyes, then the menu.
  - Say "thanks Jev": heart eyes.
  - Quit and relaunch: it waves once.

### PR 8a–8e: Optional features (separate PRs, only if you approve each)
- **8a @-mention:** typing `@` in the full-window input shows a picker of apps (`commands/apps.py`) and files (`mdfind -name`, limited to 20, local only). Choosing one inserts a token that becomes "open <name>" or "show <path> in Finder" through existing commands. Tests cover the query parse and token→phrase. This PR updates the placeholder.
- **8b Copy → translate chip:** when the clipboard gets non-English text (a cheap heuristic in pure Python), a chip "Translate" appears in the popover for 20 s. Clicking it runs a normal turn "translate this to English", local-first through the existing `model_router`. Nothing runs automatically, and it respects the `clipboard_history` paused state. It never runs on password-manager copies (existing clipboard rules).
- **8c Start my day:** adds the alias "start my day" / "morning brief" to the existing brief path, plus a chip. There's no new data source.
- **8d Tidy Downloads/Desktop, scan-only:** "tidy my downloads" lists proposed groupings (by type and age) in the window and speaks a summary. **It moves and deletes nothing.** Moving files is a later PR that needs your explicit approval. Tests use `tmp_path` trees.
- **8e Wand:** `shake_detected(samples)` (at least 4 direction reversals over 120 pt or more within 0.6 s, from the existing 20 Hz poll) puts the orb into "point" mode with a crosshair. A click captures the window under the cursor (`screenshot_command("window")`), and the PR 5a menu opens. Esc cancels. It's off by default behind a pref.

---

## 5. Hard rules (copied word for word into every Haiku prompt)

```
HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.
```

## 6. Haiku 5.5 build prompts (paste one at a time, after the previous PR is merged)

Every prompt assumes the Mac checkout at `~/Developer/hey-jev`, freshly pulled from `main`.

### Prompt: PR 1, layer rendering

```
You are Claude Haiku 5.5, building PR 1 of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev).

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-01-render

Read first: docs/plans/eney-bubble-v2.md (sections 2, 3 and "PR 1"), docs/plans/eney-bubble-v2-rea-notes.md, orb_view.py, tests/test_orb.py, tests/conftest.py, mini_bar.py (ORB_PANEL and placement constants), and how assistant_ui.py creates mini_panel and calls make_orb_view and _sync_orb.

Build:
1. New orb_motion.py: pure Python, must import with no AppKit. Constants for every PR 1 number (body 56pt, eyes 11pt, pupils 4.4pt, highlight about 20x12pt, shadow 44x10 radius 8 opacity 0.35), ORB_PALETTE (Jev's existing cyan→blue→indigo from orb_view.py as 0–1 floats), layer_geometry(bob=0.0) returning frames in the 72pt design space, pupil_offset(eye_center, cursor, max_offset=3.0, reach=300.0).
2. New orb_layers.py: lazy AppKit/Quartz imports only. Build the layer tree from section 2 (shadowLayer; bodyGroup holding bodyLayer, eyes, pupils and glyphLayer; highlightLayer as a SIBLING of bodyGroup). Pre-render the body gradient to a CGImage once per backing scale and palette; re-render in viewDidChangeBackingProperties and on appearance change.
3. orb_view.py: make JevOrbView layer-backed and use orb_layers. Keep make_orb_view(), orb_state(), configure(), stop(), the accessibility label and accessibilityPerformPress working exactly as now. Move the existing state glyphs (mic, ellipsis, mouth, "!") into glyphLayer. Keep the old drawRect_ path only for the solid (Reduce Transparency) case. No animation in this PR: pupils centered, no bob.
4. In assistant_ui.py, turn the orb panel's window shadow off (the layer draws it). Change nothing else there.
5. New tests/test_orb_motion.py covering the PR 1 unit tests in the plan. Keep tests/test_orb.py passing.

Out of scope: any motion, cursor tracking, drag or window changes.

Acceptance: the PR 1 acceptance list in the plan.

Before the PR: run python -m pytest (it must be green; CI runs 3.9 and 3.12 on Ubuntu with only pytest). Then push and open a DRAFT PR titled "Eney bubble v2 · PR 1: layer-rendered glossy orb". Its body has: summary, files, tests run, and the plan's "Hand test" checklist for PR 1 plus the base checks, as checkboxes for Fernando.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 2.
```

### Prompt: PR 2, idle character (passives, random accents, eye tracking)

```
You are Claude Haiku 5.5, building PR 2 of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PR 1 is merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-02-idle-character

Read first: the plan (section 2 "Character model", section 3 rows Idle bob, Breath and float drift, Idle accent and Pupils, plus "PR 2"), docs/plans/eney-bubble-v2-rea-notes.md, orb_motion.py, orb_layers.py, orb_view.py (OrbTicker, configure, animateOrb_), tests/test_orb.py, and assistant_ui.py _sync_orb and the hide/quit paths that call orb.stop().

Build:
1. orb_motion.py: BOB_AMPLITUDE=2.5, BOB_PERIOD=2.6, SHADOW_MIN_SCALE=0.94, BREATH_FRAMES=450, FLOAT_FRAMES=1500, CLIP_FPS=60 (assumed, see the notes), idle_active(visible, motion, docked, asleep), cursor_moved(prev, now, eps=0.5).
2. New orb_character.py (pure; no AppKit): the eye-shape library eye_shape(name, size) for open, closedDown, closedUp, smileClosed and wide (pure Bézier control points, the SAME point count for every shape); the ACCENTS table from the plan (name, frames or seconds, weight, lookIntensity) for blink, blink_stagger, double_blink, look_around, yawn, bounce, jiggle and happy; next_accent_delay(rng) uniform in [4, 9] s; pick_accent(rng, previous), weighted and never repeating the previous one; breath_speed(rng) uniform in [0.5, 1.3]; look_intensity(state, clip). Always take an injected random.Random so tests are deterministic.
3. orb_layers.py: infinite animations in the render server: the bob on bodyGroup position.y (±2.5pt, 1.3s autoreverse, easeInEaseOut), an in-phase shadow scale and opacity, breath (scale y 1.0↔1.015, x 1.0↔0.995, 7.5s ÷ breath_speed, re-picked each cycle), and float x drift (±1.0pt, 25s). The highlight never animates. Eyes get CAShapeLayer masks whose path morphs between eye shapes. One builder per accent returns a CAAnimationGroup.
4. orb_view.py: delete the 30 fps animateOrb:/setNeedsDisplay_ loop. Add ONE 20 Hz NSTimer (via OrbTicker) that reads NSEvent.mouseLocation(), exits early via cursor_moved, and sets the pupils from pupil_offset × look_intensity inside a CATransaction (0.08s linear). Add ONE single-shot accent NSTimer, rescheduled with next_accent_delay after each accent, that fires only while idle (not during a drag, menu or popover). Stop both on hide, Reduce Motion, quit, viewWillMoveToWindow_(None), and NSWorkspaceScreensDidSleepNotification; restart on wake. Blinks are now random accents (decision R5: keep blinking), so replace the fixed 7s blink in orb_pose and update tests/test_orb.py to match.
5. No global event monitors and no new permissions.

Tests: the PR 2 unit tests in the plan, in tests/test_orb_motion.py and the new tests/test_orb_character.py.

Out of scope: drag, press, docking, window motion.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 2: idle character with random accents and tracking eyes". Put the plan's PR 2 hand test plus the base checks in the body as checkboxes, including "Activity Monitor: Jev under 1% CPU after 30 s idle".

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 3a.
```

### Prompt: PR 3a, press, drag and drop physics

```
You are Claude Haiku 5.5, building PR 3a of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–2 are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-03a-press-drag

Read first: the plan (section 3 rows Press, Release, Drag and Drop, and "PR 3a"), the REA notes if present, orb_motion.py, orb_layers.py, assistant_ui.py MiniBarBackground._collapsed_click_or_drag and _finalize_mini_bar_drag, mini_bar.py drag_origin, finish_drag, capsule_click_moved and smooth, and tests/test_orb.py.

Build:
1. orb_motion.py: spring(t, x0, x1, stiffness, damping, mass=1.0, v0=0.0) -> (x, v), closed form for under-, critically- and over-damped cases; spring_done(x, v, x1, eps=0.25); follow_step(pos, vel, target, dt, stiffness=400, damping=36) (semi-implicit Euler, 2D tuples); drag_stretch(vx, vy) -> (sx, sy, angle) with sx = 1 + min(0.22, speed/3000), sy = 1/sx; drag_roughness(samples) -> (direction_reversals, seconds_above_3500pt_s), stored on the delegate after each drag for PR 7b. Put every spring from section 3 in as named constants. All functions return finite values for NaN or inf input.
2. orb_layers.py: press_squash() (scale 1.12, 0.88 over 0.10s easeOut), release_spring() (CASpringAnimation k=500, c=26), set_stretch(sx, sy, angle) (transform R(θ)·S·R(−θ) with actions disabled), drop_jiggle() (CASpringAnimation k=500, c=18).
3. assistant_ui.py _collapsed_click_or_drag: squash on mouse down. Keep the 4pt click threshold. While dragging, the target is drag_origin(...), and a 60 Hz NSTimer moves the window with follow_step and updates the stretch from the smoothed velocity (mini_bar.smooth a=0.4). On mouse up after a drag, jiggle, then spring the window to finish_drag's target (k=300, c=24) and call the existing _finalize_mini_bar_drag when it lands. Invalidate the timer once spring_done. On a click with no movement, do what it does today (release spring, then expandMiniBar_). With Reduce Motion on, keep today's exact-follow behavior with no stretch or jiggle.

Tests: the PR 3a unit tests in the plan. Existing tests/test_orb.py drag and snap tests must still pass.

Out of scope: peek-dock, capture zone, changing what a click opens.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 3a: squash, stretch, spring drag and drop jiggle", with the plan's PR 3a hand test plus the base checks as checkboxes.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 3b.
```

### Prompt: PR 3b, peek-dock

```
You are Claude Haiku 5.5, building PR 3b of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–3a are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-03b-peek-dock

Read first: the plan (section 3 rows Peek rest, Peek slide-in and Peek slide-out, plus "PR 3b"), the REA notes if present, orb_motion.py, mini_bar.py (snap_origin, finish_drag, screen_for_frame, enabled_from_pref, ORB_* constants), assistant_ui.py (_finalize_mini_bar_drag, the PR 2 cursor poll timer, how the existing menu toggles prefs), and tests/test_orb.py.

Build:
1. orb_motion.py: peek_edge_allowed(edge, screen, screens) (False when another visible frame touches that edge); peek_frame(origin, size, screen, edge) (70% of ORB_PANEL past the edge, at least 18pt visible); in_hot_zone(cursor, edge, screen, orb_center_y) (within 24pt of the edge and ±100pt of y); should_retract(cursor, orb_center, seconds_outside, busy) (more than 120pt away for 1.5s and not busy).
2. mini_bar.py: PEEK_PREF_KEY = "orb_peek_dock" (default on), parsed like enabled_from_pref, and a helper giving the rest origin for a snapped origin. The saved ORIGIN_KEY stays the inset position.
3. assistant_ui.py: after finish_drag lands on a left or right edge that's allowed, slide to the peek rest (k=200, c=26). The existing 20 Hz poll checks the hot zone, slides in with k=300, c=22, and retracts per should_retract. "Busy" means the popover, a menu, a drag, listening, thinking or speaking. Add the menu toggle "Tuck Jev into the edge", which persists. With Reduce Motion on, use a 0.15s alpha fade instead of sliding.

Tests: the PR 3b unit tests in the plan, in tests/test_orb_motion.py.

Out of scope: the capture zone, expand.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 3b: peek-dock at the screen edge", with the plan's PR 3b hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 4.
```

### Prompt: PR 4, edge capture zone

```
You are Claude Haiku 5.5, building PR 4 of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–3b are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-04-capture-zone

Read first: the plan (section 3 rows Capture zone in/out and Capture drop, plus "PR 4"), the REA notes if present, orb_motion.py, the drag code in assistant_ui.py from PR 3a, commands/captures.py (take_screenshot, screenshot_command("area"), permission_failure), and how assistant_ui.py runs a screenshot today.

Build:
1. New capture_zone.py (pure): ZONE_W=260, ZONE_H=56, ZONE_RADIUS=14, ZONE_TEXT="Drag to capture · Esc to cancel", is_outer_edge(edge, screen, screens), zone_state(prev_shown, cursor, velocity, screen, screens) (show at ≤4pt from an outer edge, or approaching faster than 1500pt/s within 40pt; hide only beyond 80pt), zone_frame(edge, cursor, screen) clamped to the visible frame.
2. assistant_ui.py: a nonactivating NSPanel at BAR_LEVEL, ordered just below the orb, ignoresMouseEvents. Content: an NSVisualEffectView (HUD material, dark appearance) plus a 55% black fill, a CAShapeLayer dashed border (1pt, white 35%, lineDashPattern [5, 4]), the SF Symbol camera.viewfinder and ZONE_TEXT. Slide it in with a spring (k=500, c=40, 0.22s) from the edge and out with easeIn over 0.18s. Update it during the PR 3a drag loop. On a drop while it's shown: spring the orb back to its pre-drag origin, hide the zone, then run the EXISTING take_screenshot(mode="area") path, so the file lands in Captures and the saved line shows as today. Then open the EXISTING post-capture choice panel, as it opens after any screenshot today. Esc during the drag hides the zone and returns the orb.
3. Expose was_capture_zone_drop on the delegate for the drop that just happened, so PR 5a can skip its drop menu (decision R3: the capture zone is its own thing).

Tests: new tests/test_capture_zone.py with the PR 4 unit tests in the plan.

Out of scope: the action menu, mark up.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 4: edge capture zone", with the plan's PR 4 hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 5a.
```

### Prompt: PR 5a, action menu

```
You are Claude Haiku 5.5, building PR 5a of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–4 are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-05a-action-menu

Read first: the plan (section 3 rows Action menu open, Menu hover and Menu close, plus "PR 5a" and decision R3), mini_bar.py (capture_choice_actions, popover_side, CHOICE_SECONDS, choice_due), assistant_ui.py (how the post-capture choice panel dispatches ask_jev, share_copy and ask_google), capture_zone.py, and orb_motion.py.

Build:
1. mini_bar.py: orb_action_menu() returns exactly four rows in order: {"id": "ask_jev", "title": "Ask"}, {"id": "share_copy", "title": "Copy Image"}, {"id": "ask_google", "title": "Find Image"}, {"id": "markup", "title": "Mark up"}, each with an SF Symbol name (bubble.left, doc.on.doc, magnifyingglass, pencil.tip). Add menu_on_drop(moved, on_capture_zone), which returns moved and not on_capture_zone.
2. orb_motion.py: menu_layout(orb_frame, screen, n=4, button=40, gap=10) returning the panel frame, button frames, the side (via popover_side) and stagger delays of 0, 30, 60 and 90 ms.
3. assistant_ui.py (decision R3): after ANY drop that menu_on_drop allows (a real drag past the 4pt threshold, not a click, and not a capture-zone drop from PR 4), once the PR 3a jiggle and snap land, show a nonactivating panel at BAR_LEVEL above the orb. It has a 14pt-radius dark NSVisualEffectView (HUD), round 40pt buttons with labels, a fan-out per section 3 (scale 0.6/alpha 0 to the slot, CASpring k=500, c=30, staggered), and hover via tracking areas (white 8% to 18%, 0.12s). Clicking a button closes the panel INSTANTLY (orderOut_, no animation). Then, for ask_jev, share_copy or ask_google, it runs the existing take_screenshot(mode="area") and, if a file was saved, passes it to the same handler the post-capture panel uses for that id (an Esc-cancelled capture does nothing). Until PR 5b, markup takes an area capture and runs `open -a Preview <file>`. Close on Esc, a click away (the existing ClickAwayView pattern), or CHOICE_SECONDS. PR 3b's tuck waits while the menu is open. Set accessibility labels.

Tests: the PR 5a unit tests in the plan.

Out of scope: the mark up overlay.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 5a: post-capture action menu", with the plan's PR 5a hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 5b.
```

### Prompt: PR 5b, mark up overlay

```
You are Claude Haiku 5.5, building PR 5b of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–5a are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-05b-markup

Read first: the plan ("PR 5b" and the window levels table), commands/captures.py (captures_folder, capture_name, _saved_sentence), and the PR 5a menu code in assistant_ui.py.

Build:
1. New markup.py (pure): a Strokes class with begin(point), extend(point) (drop points closer than 1.5pt), end(), undo(), clear(), bounds(), is_empty().
2. assistant_ui.py: Mark up opens one borderless overlay per screen at window level 101 with fullScreenAuxiliary, a clear background, and NSCursor.crosshairCursor. Dragging draws CAShapeLayer strokes (3pt, systemRed, round caps). ⌘Z undoes. Esc closes with no file. Return composites a silent full screenshot (the existing screenshot_command full mode, into ~/Documents/.cos-tmp) with the strokes, saves ONE PNG into the Captures folder via capture_name, shows the existing saved sentence, then removes the temp file (it's listed in the PR body). Refuse to save when there are no strokes. Nothing is uploaded. Replace PR 5a's Preview fallback with this.

Tests: new tests/test_markup.py with the PR 5b unit tests in the plan.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 5b: Mark up on screen", with the plan's PR 5b hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 6a.
```

### Prompt: PR 6a, expand and collapse

```
You are Claude Haiku 5.5, building PR 6a of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–5b are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-06a-expand

Read first: the plan (section 3 rows Expand, Docked and Collapse; the window levels table; "PR 6a"; decision R2), the REA notes if present, full_window.py (SIDEBAR_W, TITLEBAR_H, full_layout), assistant_ui.py (expandMiniBar_, _build_full_window, _show_full_window, _layout_full_window, windowWillClose_, _finalize_mini_bar_drag, ORIGIN_KEY handling), mini_bar.py place_bar, orb_motion.py, and tests/test_full_window.py.

Build:
1. orb_motion.py: expand_rects(orb_frame, target_frame) -> (start_rect, end_rect), where start is 10% of the target size centered on the orb's center and clamped on-screen; dock_point(window_frame, dock=36.0) -> orb frame centered on x = win.x + SIDEBAR_W − 18, y = win.top − TITLEBAR_H − 18 − 12; collapse_target(saved_origin, screens), falling back to mini_bar.place_bar.
2. full_window.py: DOCK_ORB = 36.0 and dock_rect(layout).
3. assistant_ui.py:
   - A single click on the idle orb calls the new expand. Right-click on the orb opens the existing popover. ⌃⌥J stays as is.
   - Expand: build the window if needed and lay it out (off-screen the first time), snapshot it with cacheDisplayInRect into a ghost borderless panel at BAR_LEVEL below the orb, then animate the ghost's layer with transform.scale 0.1→1.0 (CASpringAnimation k=400, c=32), anchored so it grows out of the orb's center, and opacity 0→1 over 0.18s easeOut. On completion, makeKeyAndOrderFront_ the real window and remove the ghost. In parallel, spring the orb to dock_point at 0.5 scale, stop its bob (pupils keep tracking), and addChildWindow_ordered_ it to full_window.
   - A click on the docked orb, ⌘W, or closing the window runs the exact reverse, then removes the child, restores BAR_LEVEL, springs the orb to collapse_target at 1.0 scale and resumes the bob.
   - Guard against re-entry with a simple state machine: idle, expanding, open, collapsing.
   - With Reduce Motion on, use a 0.15s crossfade and jump the orb.

Tests: the PR 6a unit tests in the plan, plus state machine transition tests.

Out of scope: window content changes (PR 6b).

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 6a: expand from the orb and dock on the divider", with the plan's PR 6a hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 6b.
```

### Prompt: PR 6b, full window content

```
You are Claude Haiku 5.5, building PR 6b of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–6a are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-06b-window-content

Read first: the plan ("PR 6b"), full_window.py, tests/test_full_window.py, assistant_ui.py (_build_full_window, _layout_full_window, _refresh_full_window, miniChip:, miniMicDown:/miniMicUp:), mini_bar.py (greeting_text, popover_chip_ids, chip_command_plan, POPOVER_CHIPS, TypedHistory).

Build:
1. full_window.py pure layout: sidebar sections "Get started" (3 rows: Try a voice command, Capture your screen, Plan my day), a "+ New chat" button, and categories (Today, Captures, Games, Mac, Recent, where Recent is the existing history list). Main column: the greeting from greeting_text() centered high, a pill input (height 44, radius 22) with a mic button at its right, and the chip row below it via chip_frames. Keep the dock_rect from PR 6a clear of the sidebar content.
2. Placeholder: "Ask Jev anything…" (it becomes "Type @ to search files, apps…" only in PR 8a).
3. assistant_ui.py: wire the views. Get started rows and categories send existing phrases (e.g. "brief me", "open my screenshots", "list games", "cleanmymac scan"). + New chat clears the on-screen conversation only. Chips use chip_command_plan. The mic uses miniMicDown:/miniMicUp:. Use the REA palette tokens (token()) for light and dark.

Tests: the PR 6b unit tests in the plan.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 6b: full window sidebar and chat", with the plan's PR 6b hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 7.
```

### Prompt: PR 7, state machine and voice states

```
You are Claude Haiku 5.5, building PR 7 of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–6b are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-07-states-voice

Read first: the plan (section 2 "Character model", in particular the state table; section 3 rows Listening, Thinking, Searching / working and Speaking; and "PR 7"), docs/plans/eney-bubble-v2-rea-notes.md, orb_character.py, orb_view.py (orb_state, configure), orb_layers.py, orb_motion.py, assistant_ui.py (_sync_orb, _meter_unit), and siri.py around the Fish TTS section and where play_fish_reply plays the WAV with afplay. Change siri.py ONLY as described below.

Build:
1. orb_character.py: resolve(status, held, reduce_motion, menu_open) -> one of idle, listening, thinking, searching, speaking, still (built on the existing orb_state; Reduce Motion or screens asleep → still). STATE_CLIPS per the plan's state table (listen_1–3, think_1–3, search_1–2, talk_1–4), each with its lookIntensity (idle 1.0, listening 0.6, thinking 0.0, searching 0.3, speaking 0.5, still 0.0). next_clip(state, rng, previous) never repeats; clip_switch_delay(state, rng): thinking exactly 7s, searching 4s, listening 3s, speaking uniform 2–4s. Add the sceptic eye shape (same point count).
2. orb_motion.py: voice_pose(state, t, level) -> dict (eye_shape, eye_scale_y, pupil_size, pupil_bias, body_scale, spinner_on, mouth_h); wav_envelope(path, hz=30) using the stdlib wave module and plain-Python RMS (no audioop), supporting 8/16-bit mono and stereo, normalized 0–1, returning [] on any error; pulse_mouth(t) as a 3.5 Hz fallback between 2 and 5pt.
3. orb_layers.py: apply clips: listening (wide eyes scale y 1.15, pupils 5.2pt, body 1 + 0.04·level, implicit 0.12s); thinking (pupils biased +1.8/+1.8 or sceptic eyes, a 270° spinner arc CAShapeLayer, 1.5pt white 70%, rotating 1.2s linear); searching (a pupil scan sweep over 1.6s plus the spinner); speaking (a CAKeyframeAnimation of the mouth height from wav_envelope, built once per reply, with the pulse fallback and small squints on peaks). The spinner exists only in thinking and searching. lookIntensity eases over 0.25s on every state or clip change. Idle accents (PR 2) are suspended outside idle. Existing shape cues stay. With Reduce Motion on (still), use static poses.
4. orb_view.py: configure() calls resolve and runs ONE single-shot clip-switch timer per state, invalidated on every state change.
5. siri.py: add only a module-level LAST_REPLY_WAV, set to the WAV path right before it's played. No other change to playback, Fish requests, keys or network. The UI reads it when the status becomes Speaking.

Tests: the PR 7 unit tests in the plan (seeded random.Random; generate the WAVs in tmp_path). The existing orb_state tests stay unchanged.

Out of scope: one-shot reactions (PR 7b). Keep today's error cue for now.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 7: state machine with listening, thinking and speaking", with the plan's PR 7 hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Don't start PR 7b.
```

### Prompt: PR 7b, one-shot reactions and eye-shape emotions

```
You are Claude Haiku 5.5, building PR 7b of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). PRs 1–7 are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-07b-reactions

Read first: the plan (section 2 "Character model", in particular the reaction table and the eye-shape library; section 3 rows Reactions and Error; and "PR 7b"), docs/plans/eney-bubble-v2-rea-notes.md, orb_character.py, orb_layers.py, orb_view.py, orb_motion.py (drag_roughness), mini_bar.py (status_is_final, POPOVER_CHIPS mac_health), and in assistant_ui.py: the Option-key handling, the wake-word status path, where a command finishes, the drop path from PRs 3a and 5a, and the first show after launch.

Build:
1. orb_character.py: the eye shapes happy, sad, heart and spiral (same point count as open); the wave and balance_eyes accents; a REACTIONS table exactly as in the plan (get_ready, success, failure, dizzy, heart, low_disk, wave), each with eye keyframes, body channel, duration, priority and cooldown; ReactionQueue(clock) with offer(name, now) -> bool (honours cooldowns; a higher or equal priority replaces the pending reaction), current(now) and cancel_all(); is_thanks(text) (word-boundary match on "thanks", "thank you", "love you jev"; "no thanks" and empty text are negatives); rough_drag(reversals, seconds_fast) (≥6 reversals or ≥0.5s above 3500pt/s); low_disk(free_bytes, total_bytes) (<10 GB or <5%).
2. orb_layers.py: one builder per reaction (a CAAnimationGroup of eye path morphs plus a body channel: hop, spin, droop, wobble or scale pulse) and the small original sweat-drop glyph for low_disk. When it ends, return to the current state's clip. With Reduce Motion on, change the eye shape only, with no movement.
3. Wiring in orb_view.py and assistant_ui.py:
   - get_ready on right Option down or the wake word
   - success when a command ends on Ready with a real reply
   - failure on "Something went wrong" or "Time's up" (this replaces the plain error pose; the "!" glyph stays)
   - dizzy on a drop when rough_drag is true (it plays BEFORE the PR 5a menu opens)
   - heart when the turn's text passes is_thanks
   - low_disk from shutil.disk_usage("/") on a background thread at launch, then at most hourly; it also sets a flag that highlights the Mac health chip, which still runs the scan only
   - wave once on the first show after launch
4. Nothing is cleaned, moved or deleted. No network calls, sockets or permissions are added.

Tests: the PR 7b unit tests in the plan (a fake clock for ReactionQueue; shutil.disk_usage stubbed so it never touches the real disk).

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 7b: reactions and eye-shape emotions", with the plan's PR 7b hand test plus the base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR. Optional PRs 8a–8e need Fernando's separate go-ahead.
```

### Prompt: PR 8x, optional feature (fill in the letter)

```
You are Claude Haiku 5.5, building optional PR 8<LETTER> of docs/plans/eney-bubble-v2.md in ~/Developer/hey-jev (github.com/fernandoceja/hey-jev). Fernando approved this specific feature. PRs 1–7b are merged.

Setup: git checkout main && git pull && git checkout -b jev/eney-v2-08<letter>-<slug>

Read first: the plan's "PR 8a–8e" entry for 8<LETTER>, then the existing modules it names (commands/apps.py, commands/clipboard_history.py, commands/model_router.py, commands/brief.py, commands/captures.py, mini_bar.py chips, orb_motion.py) and their tests.

Build exactly the plan's 8<LETTER> entry, and nothing else. Put the logic in pure, headless-testable functions, with UI wiring in assistant_ui.py only. Reuse existing commands and phrases rather than adding new backends. Local-first: model calls go through the existing model_router. For 8d (tidy): scan and list only — never move, rename or delete a file. For 8b: suggest only, never auto-run, respect the clipboard paused state and the existing password-manager rules. For 8e: off by default behind a pref.

Tests: unit tests for every pure function, using tmp_path for any files.

Before the PR: python -m pytest must be green. Push and open a DRAFT PR titled "Eney bubble v2 · PR 8<LETTER>: <feature>", with a hand-test checklist plus the plan's base checks.

HARD RULES — follow all of them, no exceptions:
- Don't merge, and don't push to main. Every change goes on a branch and a draft PR. Fernando approves each one, and his Chief of Staff merges.
- Tests and CI must pass before you open any PR.
- Keys stay in the Keychain. Never print secrets, and never re-run `siri.py --bridge-secret`.
- No new listening sockets. The only one allowed is the existing `fm serve` on 127.0.0.1:1976.
- No bridge security changes. Nothing new goes on the iPhone bridge, and money commands and My Love stay off it.
- Zoe mode refusals stay intact.
- No paid APIs or new spending. Free open-source dependencies only, and only with a reason.
- Don't touch ~/Documents/AI-Projects/Jarvis (that's the backup).
- Put temp files only in ~/Documents/.cos-tmp.
- Never enter passwords, and never change macOS security settings.
- Don't delete anything without listing it first.
- Don't copy Eney's assets or code. All art is original vector or layer drawing.

Stop after opening the draft PR.
```
