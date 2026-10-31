# PR 0: Eney study notes (read-only, from Fernando's Mac, Oct 30 2026)

I tried REA `analyze` on /Applications/Setapp/Eney.app, but it failed with `provider_unavailable` because no Ghidra, Hopper or IDA is installed. These notes come from reading Eney's resource folder and file names instead. I didn't copy any assets, and Jev must use original art.

## How it's built
- Eney's character is a **3D model with baked animation clips**: 111 files in `Resources/CharacterContent`, made up of `.usdc` scenes plus `.json` metadata files, about 77 MB.
- It ships its own `CharacterKit_CharacterCore` bundle and a `PointAnimator` framework. It also has `EneysWand`, `ClipboardHistory`, `Transcription`, `MCP`, `PermissionsKit` and `DisplayLink` frameworks, which suggests rendering driven by the display's refresh.
- In each clip's JSON, `duration`, `in` and `out` are probably frame counts, likely at 60 fps. That's unconfirmed. Clips also have `speed` and `intensity` (sometimes a random range like "0.7...1.3"), `lookIntensity` (how much the eyes keep following the cursor during the clip, from 0 to 1), `tags`, and `blendShapes`, which are eye shapes: ClosedEye Up/Down, SmileClosed, Happy, Sad, Sceptic, Heart, Split, plus body Squash and Scale_Y.

## State machine (from configuration.json)
- **idle** is the default. Two clips run under it all the time: `breath`, about 450 frames with a random speed of 0.5–1.3, and `floating`, about 1,500 frames. Every **4–9 s** one random accent plays on top. The accents are a blink (20 frames), a blink with one eye after the other (28 frames), a look-around (90 frames), a yawn, a bounce, a wave, a happy look, jiggles, and a balancing-eyes bit.
- **thinking** picks one clip tagged "thinking" and switches every 7 s. Those clips have lookIntensity 0, so the eyes stop following the cursor.
- **searching** uses the search and curiosity clips.
- **voiceInput** is listening: Listen_01–03. **readingAloud** is speaking: Talk_01–04, switching every 2–4 s.
- **still** is a frozen pose with no motion.
- One-shot **reactions**: success (spin jump, happy, cozy), failure (sad, frustrated, skeptic), getReady (bounce, shake, wave), memoryUpdate, positive feedback (heart eyes), negative feedback, dizzy (when it's dragged or shaken too much), quit, headphones (meetings), outOfDiscSpace, annoyed, curiosity, wave, and others.

## What this means for Jev's plan
- Model Jev's motion as the same three layers: **always-on passives** (breath plus float), **random idle accents every 4–9 s**, and **one clip per state** with a per-clip `lookIntensity` that turns eye-tracking down while thinking.
- Express emotion mostly through **eye shapes** (closed, smile, sad, skeptic, heart) plus body squash and Scale_Y.
- Add one-shot reactions: success, failure, getReady/wake, dizzy after a rough drag, and out of disk space, which ties into the Mac health chip.
- Jev can do all of this with its own 2D Core Animation layers and its own palette. It doesn't need USD or 3D.
