# Jev animations from Eney: replicate plan (items 1 to 4)

Clean-room. The source is the Nov 6 2026 REA study of Eney's UI, which was static analysis only (symbol names,
configuration, resource names). It has no measured timing or easing, so every number below is Jev's own choice.
Nothing is copied from Eney: no code, art, clip data or strings. All four are original Core Animation work.

Parked for a later REA run (not in this plan): tool and activity rows, message reveal and scroll-to-bottom,
queued message actions, orb flies to the selection.

Rules for every PR: one item per PR, local tests before merge, no GitHub Actions, no push to main, Reduce Motion
turns the motion off, nothing plays audio.

## 1. Loading shimmer
- What Eney does (study): a sweep offset state in a shimmer bar with a configurable duration, shown while loading.
- Jev version: while the result panel's body text is a pending line (ends in an ellipsis, such as "Reading the
  capture..."), a soft highlight band sweeps across the text on a repeating mask animation. The sweep ends when the
  real answer replaces the text, because the panel is rebuilt.
- Constants in `orb_motion.py`: SHIMMER_SECONDS 1.4, SHIMMER_BAND 0.5, SHIMMER_DIM 0.45.
- Reduce Motion: no sweep. The pending text stays at a steady dimmed alpha.
- Tests: pending-text rule, mask locations, constants sane, Reduce Motion branch, source wiring.

## 2. Speaking clip rotation
- What Eney does (study): the reading-aloud state picks a random talk clip and switches every 2 to 4 s.
- Jev version: add a `speaking` entry to the clip switch table so the orb rotates through its speaking clips on a
  random 2 to 4 s timer. Jev's thinking, searching and listening already do this.
- Tests: switch delay range, never repeats the previous clip, other states unchanged.

## 3. Memory-update and search reactions
- What Eney does (study): a one-shot memory-update reaction, and a curiosity clip in the searching state.
- Jev version: two new original reactions in `REACTIONS`: `remember` (a quick nod and a smile-closed eye) when Jev
  saves a note or memory, and `curious` (a small head-tilt wobble and a wide eye) when a lookup starts. Both go
  through the existing ReactionQueue with priorities and cooldowns, so they cannot spam.
- Tests: table entries, cooldowns, trigger rules, queue priority against success and failure.

## 4. Copy-button pop
- What Eney does (study): a copy button with an animates-feedback option and a copied state.
- Jev version: the result panel's Copy pill briefly shows a check mark and the title "Copied", with a short scale
  pop (1.0 to 1.12 to 1.0, easeOut), then the panel closes after a beat. Reduce Motion: the label swap only.
- Tests: constants, label swap, Reduce Motion branch.

## Live-test list
Written after each PR merges and given to Fernando with the rebuild.
