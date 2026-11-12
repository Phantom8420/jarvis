"""Try providers in order; fall to the next on rate limit or outage.

Configured by JARVIS_PROVIDERS (comma list, default "gemini"), e.g.
"groq,cerebras,openrouter,gemini". Each non-gemini name needs
<NAME>_API_KEY and may set <NAME>_MODEL. Keys are yours, one per provider;
this only spreads load across them, it doesn't dodge any single limit.
"""

from __future__ import annotations

import logging
import os
import time

import brain as gemini_brain
import config
from brain import ProviderError

log = logging.getLogger("jarvis.chain")

_COOLDOWN_S = 60

# name -> (base_url, default_model). Models change often; override with <NAME>_MODEL.
_OPENAI_COMPAT = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "cerebras": ("https://api.cerebras.ai/v1", "llama-3.3-70b"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct:free"),
}


def _build(name: str):
    if name == "gemini":
        return gemini_brain.Brain()
    if name not in _OPENAI_COMPAT:
        raise ValueError(f"unknown provider {name!r}")
    key = (os.environ.get(f"{name.upper()}_API_KEY") or "").strip()
    if not key:
        raise ValueError(f"{name.upper()}_API_KEY is not set")
    import openai_brain

    url, default_model = _OPENAI_COMPAT[name]
    model = (os.environ.get(f"{name.upper()}_MODEL") or "").strip() or default_model
    return openai_brain.OpenAIBrain(name, url, key, model)


class ChainBrain:
    def __init__(self, names: list[str] | None = None) -> None:
        names = names or [n.strip().lower() for n in config.PROVIDERS.split(",") if n.strip()]
        self.providers = []
        for n in names:
            try:
                self.providers.append(_build(n))
            except Exception as e:  # skip providers that aren't configured
                log.warning("provider %s skipped: %s", n, e)
        if not self.providers:
            raise RuntimeError("no usable provider; check JARVIS_PROVIDERS and the API keys")
        self._cool_until = [0.0] * len(self.providers)
        self.history: list[tuple[str, str]] = []  # (user, reply) pairs, shared across providers

    def reset(self) -> None:
        self.history = []
        for p in self.providers:
            p.reset()

    def _replay(self, p) -> None:
        # A provider that sat out earlier turns has no memory of them; give it the text.
        if getattr(p, "_seen", 0) == len(self.history):
            return
        p.reset()
        for user, reply in self.history[-10:]:
            p.seed(user, reply)
        p._seen = len(self.history)

    def ask(self, user_input: str) -> str:
        now = time.monotonic()
        order = [i for i in range(len(self.providers)) if self._cool_until[i] <= now]
        order = order or list(range(len(self.providers)))  # all cooling: try anyway
        for i in order:
            p = self.providers[i]
            self._replay(p)
            try:
                reply = p.ask(user_input)
            except ProviderError as e:
                log.warning("%s", e)
                self._cool_until[i] = time.monotonic() + _COOLDOWN_S
                continue
            self.history.append((user_input, reply))
            p._seen = len(self.history)
            return reply
        return "Every model provider is rate limited or down right now. Try again in a minute."
