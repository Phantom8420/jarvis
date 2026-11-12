"""Jarvis hub: one HTTPS-facing brain for the phone app, Glasses and the laptop.

    JARVIS_HUB_TOKENS=phone:<secret>,glasses:<secret>   (one revocable token per device)
    python server.py                                    (binds 127.0.0.1; put Caddy in front)

Hub mode exposes only the memory/notes tools, never the host's files or shell.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading

os.environ["JARVIS_HUB"] = "true"  # must be set before config/tools are imported

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

import chain

log = logging.getLogger("jarvis.hub")


def _load_tokens() -> dict[str, str]:
    pairs = (p.split(":", 1) for p in os.environ.get("JARVIS_HUB_TOKENS", "").split(",") if ":" in p)
    return {name.strip(): tok.strip() for name, tok in pairs if tok.strip()}


TOKENS = _load_tokens()
_brain = None
_lock = threading.Lock()  # one conversation, one turn at a time
app = FastAPI(title="jarvis-hub", docs_url=None, redoc_url=None, openapi_url=None)


def device(authorization: str = Header(default="")) -> str:
    sent = authorization.removeprefix("Bearer ").strip()
    for name, tok in TOKENS.items():
        if hmac.compare_digest(sent, tok):
            return name
    raise HTTPException(401, "bad token")


class Ask(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/ask")
def ask(body: Ask, who: str = Depends(device)) -> dict:
    global _brain
    with _lock:
        if _brain is None:
            _brain = chain.ChainBrain()
        log.info("ask from %s (%d chars)", who, len(body.text))
        return {"reply": _brain.ask(body.text)}


if __name__ == "__main__":
    if not TOKENS:
        raise SystemExit("Set JARVIS_HUB_TOKENS=name:secret[,name:secret] first.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("JARVIS_HUB_PORT", "8780")))
