"""Jarvis — entry point.

    python jarvis.py            voice mode (wake word)
    python jarvis.py --text     typed mode, no microphone
    python jarvis.py --devices  list input devices and exit
    python jarvis.py --once "what's on my disk"
"""

from __future__ import annotations

import argparse
import logging
import sys

import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("faster_whisper").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("jarvis")

STOP_WORDS = {"stop", "exit", "quit", "goodbye", "shut down", "never mind"}


def strip_wake_word(text: str) -> str | None:
    """Return the command with the wake word removed, or None if not addressed."""
    lowered = text.lower()
    idx = lowered.find(config.WAKE_WORD)
    if idx == -1 or idx > config.WAKE_WINDOW_CHARS:
        return None
    return text[idx + len(config.WAKE_WORD) :].lstrip(" ,.:;-—!?").strip()


def run_text_mode(brain) -> None:
    print("Type a message, or 'exit'. Ctrl+C to quit.\n")
    while True:
        try:
            line = input("you > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not line:
            continue
        if line.lower() in STOP_WORDS:
            return
        reply = brain.ask(line)
        print(f"\njarvis > {reply}\n")


def run_voice_mode(brain) -> None:
    import ears
    import voice

    voice.say("Jarvis online.")
    voice.wait_until_done()

    for heard in ears.utterances(is_muted=voice.is_speaking):
        command = strip_wake_word(heard)
        if command is None:
            log.debug("(ignored) %s", heard)
            continue
        if not command:
            voice.say("Yes?")
            continue

        log.info("heard: %s", command)
        if command.lower().rstrip(".!?") in STOP_WORDS:
            voice.say("Goodbye.", block=True)
            return

        try:
            reply = brain.ask(command)
        except Exception:  # one bad turn must not end the session
            log.exception("turn failed")
            voice.say("Something went wrong on that one.")
            continue

        print(f"\njarvis > {reply}\n")
        voice.say(reply)


def main() -> int:
    parser = argparse.ArgumentParser(description="Jarvis")
    parser.add_argument("--text", action="store_true", help="typed input, no microphone")
    parser.add_argument("--devices", action="store_true", help="list microphones and exit")
    parser.add_argument("--once", metavar="PROMPT", help="run a single prompt and exit")
    args = parser.parse_args()

    if args.devices:
        import ears

        print("Input devices:\n" + ears.list_devices())
        return 0

    import brain as brain_mod

    try:
        brain = brain_mod.Brain()
    except Exception as e:
        log.error("Could not start: %s", e)
        log.error("Set GEMINI_API_KEY in .env or the environment.")
        return 1

    log.info(
        "model=%s thinking=%s writes=%s shell=%s approval=%s",
        config.MODEL,
        config.THINKING_LEVEL,
        config.ALLOW_WRITES,
        config.ALLOW_SHELL,
        config.REQUIRE_APPROVAL,
    )

    if args.once:
        print(brain.ask(args.once))
        return 0

    try:
        if args.text:
            run_text_mode(brain)
        else:
            run_voice_mode(brain)
    except KeyboardInterrupt:
        print()
    log.info("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
