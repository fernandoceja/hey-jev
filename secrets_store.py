"""Store API keys in the macOS login Keychain, with .env as a dev fallback."""
import os
import subprocess

from dotenv import load_dotenv

load_dotenv()  # so a .env works from the app bundle too, not just the terminal


SERVICE = "com.jevsiri.keys"
# Asked for in the Keys panel. The app will not start the mic until the required ones exist.
KEY_NAMES = ("TYPESAFE_API_KEY", "FISH_AUDIO_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY")
# Dictation only. Listed in KEY_NAMES so the Keys panel can save it, never required to launch.
# An OpenAI key sends dictation straight to OpenAI instead of through OpenRouter.
OPTIONAL = ("OPENAI_API_KEY",)
# Stored in the same Keychain service, but never required to launch.
# JEV_BRIDGE_SECRET signs iCloud inbox files. GOOGLE_OAUTH_TOKEN is the
# optional Gmail hook for the morning brief (unused unless a token is saved).
OPTIONAL_KEY_NAMES = ("JEV_BRIDGE_SECRET", "GOOGLE_OAUTH_TOKEN", "OPENAI_API_KEY")


def keychain_value(name):
    result = subprocess.run(
        ["security", "find-generic-password", "-a", name, "-s", SERVICE, "-w"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def get_secret(name):
    return os.getenv(name) or keychain_value(name)  # .env wins, so editing it always takes effect


def save_secret(name, value):
    if name not in KEY_NAMES and name not in OPTIONAL_KEY_NAMES:
        raise ValueError(f"unknown secret: {name}")
    value = value.strip()
    if not value:
        return
    result = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", name, "-s", SERVICE, "-w", value],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not save to Keychain")


def missing_secrets():
    return [name for name in KEY_NAMES if name not in OPTIONAL and not get_secret(name)]

