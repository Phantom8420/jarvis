"""Persistent facts, stored as a flat JSON list and injected into the system prompt.

Deliberately dumb: a handful of short strings beats a vector store at this size,
and it stays readable/editable by hand.
"""

from __future__ import annotations

import json
import time
from typing import Any

import config

_MAX_FACTS = 200


def _load() -> list[dict[str, Any]]:
    if not config.MEMORY_PATH.is_file():
        return []
    try:
        data = json.loads(config.MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(facts: list[dict[str, Any]]) -> None:
    config.MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = config.MEMORY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(facts, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(config.MEMORY_PATH)


def add(fact: str) -> str:
    fact = fact.strip()
    if not fact:
        return "Nothing to remember."
    facts = _load()
    for existing in facts:
        if existing.get("fact", "").lower() == fact.lower():
            return "Already remembered."
    facts.append({"fact": fact, "at": time.strftime("%Y-%m-%d")})
    _save(facts[-_MAX_FACTS:])
    return f"Remembered: {fact}"


def forget(needle: str) -> str:
    needle = needle.strip().lower()
    if not needle:
        return "Nothing to forget."
    facts = _load()
    kept = [f for f in facts if needle not in f.get("fact", "").lower()]
    removed = len(facts) - len(kept)
    if removed:
        _save(kept)
    return f"Forgot {removed} item(s)." if removed else "No match."


def all_facts() -> list[str]:
    return [f.get("fact", "") for f in _load() if f.get("fact")]


def as_prompt_block() -> str:
    facts = all_facts()
    if not facts:
        return ""
    lines = "\n".join(f"- {f}" for f in facts)
    return f"\n\nThings you've been told to remember about this user:\n{lines}"
