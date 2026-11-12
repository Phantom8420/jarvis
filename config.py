"""Configuration. Everything is overridable via .env next to this file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def _flag(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    try:
        return float(raw)
    except ValueError:
        return default


# --- brain ------------------------------------------------------------------
# The client reads GOOGLE_API_KEY or GEMINI_API_KEY from the environment on
# its own (checked in that order) — no key is read directly in this file.
MODEL = (os.environ.get("JARVIS_MODEL") or "gemini-flash-latest").strip()
# low | medium | high — Gemini's equivalent of a reasoning-depth dial.
THINKING_LEVEL = (os.environ.get("JARVIS_THINKING_LEVEL") or "medium").strip()
PROVIDERS = (os.environ.get("JARVIS_PROVIDERS") or "gemini").strip()
MAX_TOKENS = _int("JARVIS_MAX_TOKENS", 8000)
MAX_TOOL_ITERATIONS = _int("JARVIS_MAX_TOOL_ITERATIONS", 24)

# --- ears -------------------------------------------------------------------
# Hub mode (server.py): the process runs on a shared VM, so only the memory/notes
# tools are exposed. No file, window or shell access to the host.
HUB = _flag("JARVIS_HUB", False)

WAKE_WORD = (os.environ.get("JARVIS_WAKE_WORD") or "jarvis").strip().lower()
# Speech is only treated as a command if the wake word appears within this many
# characters of the start. Keeps "...as jarvis would say" from triggering.
WAKE_WINDOW_CHARS = _int("JARVIS_WAKE_WINDOW_CHARS", 25)

SAMPLE_RATE = _int("JARVIS_SAMPLE_RATE", 16000)  # whisper wants 16k
BLOCK_MS = _int("JARVIS_BLOCK_MS", 30)
INPUT_DEVICE = (os.environ.get("JARVIS_INPUT_DEVICE") or "").strip()

# Voice-activity thresholds. SPEECH_RATIO is how many times above the rolling
# noise floor a block must be to count as speech.
SPEECH_RATIO = _float("JARVIS_SPEECH_RATIO", 3.0)
MIN_SPEECH_RMS = _float("JARVIS_MIN_SPEECH_RMS", 0.008)
NOISE_FLOOR_ALPHA = _float("JARVIS_NOISE_FLOOR_ALPHA", 0.995)
SILENCE_HANG_S = _float("JARVIS_SILENCE_HANG_S", 0.9)  # end-of-utterance gap
MIN_UTTERANCE_S = _float("JARVIS_MIN_UTTERANCE_S", 0.35)
MAX_UTTERANCE_S = _float("JARVIS_MAX_UTTERANCE_S", 30.0)

WHISPER_MODEL = (os.environ.get("JARVIS_WHISPER_MODEL") or "base.en").strip()
WHISPER_COMPUTE = (os.environ.get("JARVIS_WHISPER_COMPUTE") or "int8").strip()

# --- voice ------------------------------------------------------------------
TTS_BACKEND = (os.environ.get("JARVIS_TTS") or "sapi").strip().lower()  # sapi|elevenlabs|off
SAPI_VOICE = (os.environ.get("JARVIS_SAPI_VOICE") or "").strip()
SAPI_RATE = _int("JARVIS_SAPI_RATE", 185)
ELEVENLABS_API_KEY = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
ELEVENLABS_VOICE_ID = (os.environ.get("ELEVENLABS_VOICE_ID") or "").strip()
ELEVENLABS_MODEL_ID = (os.environ.get("ELEVENLABS_MODEL_ID") or "eleven_turbo_v2_5").strip()

# --- tools ------------------------------------------------------------------
ALLOW_WRITES = _flag("JARVIS_ALLOW_WRITES", True)
ALLOW_SHELL = _flag("JARVIS_ALLOW_SHELL", True)
ALLOW_WEB_SEARCH = _flag("JARVIS_ALLOW_WEB_SEARCH", True)
# Every write/shell call stops and asks in the terminal unless this is off.
# Turning it off is the difference between an assistant and a loaded gun.
REQUIRE_APPROVAL = _flag("JARVIS_REQUIRE_APPROVAL", True)
SHELL_TIMEOUT_S = _int("JARVIS_SHELL_TIMEOUT_S", 60)
MAX_READ_CHARS = _int("JARVIS_MAX_READ_CHARS", 40000)

# --- google (gmail + calendar) ----------------------------------------------
ENABLE_GOOGLE = _flag("JARVIS_ENABLE_GOOGLE", True)
GOOGLE_CREDENTIALS_PATH = Path(
    (os.environ.get("GOOGLE_CREDENTIALS_PATH") or "").strip() or (ROOT / "credentials.json")
)
GOOGLE_TOKEN_PATH = Path(
    (os.environ.get("GOOGLE_TOKEN_PATH") or "").strip() or (ROOT / "google_token.json")
)
TIMEZONE = (os.environ.get("JARVIS_TIMEZONE") or "Asia/Kolkata").strip()

# --- memory -----------------------------------------------------------------
MEMORY_PATH = Path(
    (os.environ.get("JARVIS_MEMORY_PATH") or "").strip() or (ROOT / "memory.json")
)
NOTES_PATH = Path(
    (os.environ.get("JARVIS_NOTES_PATH") or "").strip() or (ROOT / "notes.db")
)
