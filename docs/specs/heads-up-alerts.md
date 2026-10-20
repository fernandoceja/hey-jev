# Jev Heads-Up Alerts — Proactive Notifications Engine

## Summary
A heads-up engine inside Jev on the Mac. Every few minutes it checks:
- the next calendar event
- the hazard watch
- drive time home (ETA)

It uses **only checks Jev already runs**. When something matters (e.g. "Your shift at Brea starts in 45 minutes and traffic adds 10"), Jev speaks it **once** in its voice and logs it. No repeats for the same alert.

## Requirements
- **Voice on/off command** to enable or disable heads-up alerts.
- **Quiet hours:** 10 PM to 7 AM, no spoken alerts.
- **Rate limit** so Jev doesn't nag.
- **Money filter:** never speak balances, bills, or any money details.
- **No new network ports or listening sockets.**
- **Nothing triggerable from the iPhone bridge.**
- **API keys stay in Keychain** (`com.jevsiri.keys`).
- **Tests:** must add tests; the full suite (663+) must pass before approval.

## Critic warnings
- No code tested yet.
- Never speak money details aloud (others may be in the room).
- Needs quiet hours + rate limit to avoid nagging.
- Reuse existing checks only; no new ports; no phone trigger.

## Process
Build via Antigravity on branch `feature/heads-up-alerts`. Ends in a pull request waiting for Fernando's approval.
