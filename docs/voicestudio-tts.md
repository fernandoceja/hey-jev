# Optional VoiceStudio speech

Fish remains the default and fallback. Start hey-jev with
`JEV_TTS_PROVIDER=VOICESTUDIO .venv/bin/python siri.py` to opt in, or set
`JEV_TTS_PROVIDER=VOICESTUDIO` in the local ignored `.env` and restart hey-jev.
Set it back to `FISH` (or remove it) and restart to restore Fish.
For the desktop app, use its normal launch environment or local `.env`;
an environment variable in a terminal does not change an already running app.

VoiceStudio must be running on localhost:3900. The adapter uses the installed
OmniVoice engine and its default voice. Optionally set `JEV_VOICESTUDIO_VOICE`
to an existing VoiceStudio profile ID or unique name. No profiles are created.
The adapter checks `/models` for a complete installed OmniVoice model and
existing license acceptance before uncached synthesis. It never calls an install,
license acceptance, engine selection, or consent endpoint.

Discovered from the running app's OpenAPI 3.1 specification, API version 0.5.7:

```http
POST http://localhost:3900/v1/audio/speech
Content-Type: application/json

{"model":"omnivoice","input":"Hello.","voice":"default","response_format":"wav"}
```

`input` is required (maximum 4096 characters). `voice` accepts a profile ID,
case-insensitive unique profile name, or `default`. The request schema documents
the WAV format; the 200 response schema itself is untyped and marked
`application/json`, so the adapter validates returned bytes as a nonempty WAV
before caching and playing them with the existing `afplay` path.
VoiceStudio audio is cached separately under `cache/tts/voicestudio`.
Failures retain the existing Fish call and settings. Private local-only speech,
wake word, Whisper, routing, and command behavior are unchanged.

This switch covers the shared `siri.fetch_tts` reply path; the tutor's separate
Fish synthesis helper remains unchanged.
