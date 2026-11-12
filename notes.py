"""Second-brain notes: a SQLite full-text index you can add to and search.

memory.py holds a few short standing facts that ride in every prompt. This is
the long tail: meeting notes, ideas, things read or said, searched on demand so
the prompt stays small. One local file, stdlib only (SQLite FTS5).
"""

from __future__ import annotations

import re
import sqlite3
import time

import config


def _db() -> sqlite3.Connection:
    config.NOTES_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.NOTES_PATH)
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS notes USING fts5(body, tags, at UNINDEXED)")
    return con


def add(body: str, tags: str = "") -> str:
    body = body.strip()
    if not body:
        return "Nothing to save."
    with _db() as con:
        con.execute("INSERT INTO notes(body, tags, at) VALUES (?, ?, ?)", (body, tags.strip(), time.strftime("%Y-%m-%d")))
    return "Saved."


def search(query: str, limit: int = 8) -> list[str]:
    # Quote each word so user text can't be parsed as FTS operators; OR them so any hit counts.
    words = re.findall(r"\w+", query)
    if not words:
        return []
    match = " OR ".join(f'"{w}"' for w in words)
    with _db() as con:
        rows = con.execute(
            "SELECT at, body, tags FROM notes WHERE notes MATCH ? ORDER BY rank LIMIT ?", (match, limit)
        ).fetchall()
    return [f"[{at}]{' #' + tags if tags else ''} {body}" for at, body, tags in rows]
