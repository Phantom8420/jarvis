"""Microphone → utterances → text, entirely on this machine.

Energy-based VAD segments speech, faster-whisper transcribes. Audio never
leaves the box and is discarded as soon as it's transcribed.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Iterator

import numpy as np
import sounddevice as sd

import config

log = logging.getLogger("jarvis.ears")

_model = None


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        log.info("Loading whisper model %r (first run downloads it)...", config.WHISPER_MODEL)
        _model = WhisperModel(
            config.WHISPER_MODEL, device="cpu", compute_type=config.WHISPER_COMPUTE
        )
        log.info("Whisper ready.")
    return _model


def transcribe(audio: np.ndarray) -> str:
    segments, _ = _load_model().transcribe(
        audio,
        language="en",
        beam_size=1,
        vad_filter=True,
        condition_on_previous_text=False,
    )
    return " ".join(s.text.strip() for s in segments).strip()


def resolve_device() -> int | None:
    """Honour JARVIS_INPUT_DEVICE (index or name substring), else system default."""
    spec = config.INPUT_DEVICE
    if not spec:
        return None
    if spec.isdigit():
        return int(spec)
    needle = spec.lower()
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] >= 1 and needle in dev["name"].lower():
            return idx
    log.warning("No input device matches %r; using default.", spec)
    return None


def list_devices() -> str:
    lines = []
    for idx, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] >= 1:
            lines.append(f"  [{idx}] {dev['name']}")
    return "\n".join(lines)


def utterances(is_muted=lambda: False) -> Iterator[str]:
    """Yield transcribed utterances forever.

    `is_muted` is polled per block; while it returns True the audio is dropped
    on the floor. That is how Jarvis avoids transcribing its own TTS output.
    """
    blocksize = max(1, int(config.SAMPLE_RATE * config.BLOCK_MS / 1000))
    device = resolve_device()

    frames: "queue.Queue[np.ndarray]" = queue.Queue()

    def callback(indata, _frames, _time_info, status):
        if status:
            log.debug("audio status: %s", status)
        frames.put(indata[:, 0].copy())

    stream = sd.InputStream(
        device=device,
        samplerate=config.SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=blocksize,
        callback=callback,
    )

    noise_floor = 1e-3
    collecting: list[np.ndarray] = []
    # Keep a little audio from before the trigger so the first word survives.
    preroll: list[np.ndarray] = []
    preroll_blocks = max(1, int(300 / config.BLOCK_MS))
    last_voice = 0.0
    started = 0.0

    with stream:
        name = sd.query_devices(device if device is not None else sd.default.device[0])["name"]
        log.info("Listening on %s. Say '%s ...' or Ctrl+C to stop.", name, config.WAKE_WORD)
        while True:
            block = frames.get()
            now = time.monotonic()

            if is_muted():
                collecting.clear()
                preroll.clear()
                continue

            rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
            threshold = max(noise_floor * config.SPEECH_RATIO, config.MIN_SPEECH_RMS)
            voiced = rms >= threshold

            if not voiced:
                # Only adapt the floor on quiet blocks, or speech drags it up.
                noise_floor = (
                    config.NOISE_FLOOR_ALPHA * noise_floor
                    + (1 - config.NOISE_FLOOR_ALPHA) * rms
                )
                noise_floor = max(noise_floor, 1e-6)

            if collecting:
                collecting.append(block)
                if voiced:
                    last_voice = now
                too_long = now - started >= config.MAX_UTTERANCE_S
                if too_long or now - last_voice >= config.SILENCE_HANG_S:
                    audio = np.concatenate(collecting)
                    collecting.clear()
                    if len(audio) / config.SAMPLE_RATE >= config.MIN_UTTERANCE_S:
                        text = transcribe(audio)
                        if text:
                            yield text
            elif voiced:
                collecting = [*preroll, block]
                preroll.clear()
                started = last_voice = now
            else:
                preroll.append(block)
                if len(preroll) > preroll_blocks:
                    preroll.pop(0)
