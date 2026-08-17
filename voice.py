"""Text to speech. SAPI (offline, free) by default; ElevenLabs if configured.

Speaking runs on a worker thread so the mic can re-arm while audio is still
playing — otherwise Jarvis hears itself and transcribes its own voice.
"""

from __future__ import annotations

import logging
import queue
import re
import threading

import config

log = logging.getLogger("jarvis.voice")

_queue: "queue.Queue[str | None]" = queue.Queue()
_worker: threading.Thread | None = None
_speaking = threading.Event()


def is_speaking() -> bool:
    return _speaking.is_set()


def _strip_for_speech(text: str) -> str:
    """Drop markdown and code blocks — they sound terrible read aloud."""
    text = re.sub(r"```.*?```", " (code omitted) ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"^\s*[#>*\-]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    return re.sub(r"\s+", " ", text).strip()


def _speak_sapi(text: str) -> None:
    import pyttsx3

    # A fresh engine per utterance: pyttsx3's runAndWait() leaves the shared
    # engine in a state where the second call returns immediately.
    engine = pyttsx3.init()
    engine.setProperty("rate", config.SAPI_RATE)
    if config.SAPI_VOICE:
        for v in engine.getProperty("voices"):
            if config.SAPI_VOICE.lower() in v.name.lower():
                engine.setProperty("voice", v.id)
                break
    engine.say(text)
    engine.runAndWait()
    engine.stop()


def _speak_elevenlabs(text: str) -> None:
    import numpy as np
    import sounddevice as sd
    from elevenlabs.client import ElevenLabs

    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
    chunks = client.text_to_speech.convert(
        voice_id=config.ELEVENLABS_VOICE_ID,
        text=text,
        model_id=config.ELEVENLABS_MODEL_ID,
        output_format="pcm_24000",
    )
    raw = b"".join(chunks)
    if not raw:
        return
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    sd.play(pcm, 24000)
    sd.wait()


def _run() -> None:
    while True:
        text = _queue.get()
        if text is None:
            return
        _speaking.set()
        try:
            if config.TTS_BACKEND == "elevenlabs":
                if config.ELEVENLABS_API_KEY and config.ELEVENLABS_VOICE_ID:
                    _speak_elevenlabs(text)
                else:
                    log.warning("ElevenLabs selected but key/voice missing; using SAPI.")
                    _speak_sapi(text)
            else:
                _speak_sapi(text)
        except Exception as e:  # a failed TTS must never kill the loop
            log.warning("TTS failed: %s", e)
        finally:
            _speaking.clear()
            _queue.task_done()


def say(text: str, block: bool = False) -> None:
    global _worker
    if config.TTS_BACKEND == "off":
        return
    clean = _strip_for_speech(text)
    if not clean:
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, daemon=True)
        _worker.start()
    _queue.put(clean)
    if block:
        _queue.join()


def wait_until_done() -> None:
    _queue.join()
