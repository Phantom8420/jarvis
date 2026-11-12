"""Brain for any OpenAI-compatible chat API (Groq, Cerebras, OpenRouter, ...).

Same manual tool loop as brain.py, over plain httpx so there is no new
dependency. Tool schemas are built from the tool functions' signatures and
their docstring `Args:` sections.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import typing

import httpx

import brain as gemini_brain
import config
import google_tools
import tools
from brain import ProviderError

log = logging.getLogger("jarvis.openai")

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _schema(func) -> dict:
    doc = inspect.getdoc(func) or ""
    summary = doc.split("\n\nArgs:")[0].strip()
    arg_docs = dict(re.findall(r"^\s{0,4}(\w+):\s*(.+)$", doc.split("Args:")[-1], re.M)) if "Args:" in doc else {}
    props, required = {}, []
    for name, p in inspect.signature(func).parameters.items():
        hint = typing.get_type_hints(func).get(name, str)
        if typing.get_origin(hint) is list:
            prop = {"type": "array", "items": {"type": _JSON_TYPES.get(typing.get_args(hint)[0], "string")}}
        else:
            prop = {"type": _JSON_TYPES.get(hint, "string")}
        if name in arg_docs:
            prop["description"] = arg_docs[name]
        props[name] = prop
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": summary,
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


class OpenAIBrain:
    def __init__(self, name: str, base_url: str, api_key: str, model: str) -> None:
        self.name, self.model = name, model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        funcs = [*tools.active_tools(), *google_tools.active_tools()]
        self._by_name = {f.__name__: f for f in funcs}
        self._tools = [_schema(f) for f in funcs]
        self.messages: list[dict] = []

    def reset(self) -> None:
        self.messages = []

    def seed(self, user: str, reply: str) -> None:
        self.messages += [{"role": "user", "content": user}, {"role": "assistant", "content": reply}]

    def _post(self, body: dict) -> dict:
        try:
            r = httpx.post(self._url, json=body, headers=self._headers, timeout=60)
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} network error: {e}") from e
        if r.status_code == 429 or r.status_code >= 500:
            raise ProviderError(f"{self.name} HTTP {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            # Bad key/model/schema won't fix itself on retry, but another provider may work.
            raise ProviderError(f"{self.name} rejected the request (HTTP {r.status_code}): {r.text[:200]}")
        return r.json()

    def _run_tool(self, call: dict) -> dict:
        name = call["function"]["name"]
        func = self._by_name.get(name)
        if func is None:
            out = {"error": f"No such tool: {name}"}
        else:
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
                log.info("tool: %s(%s)", name, gemini_brain._brief(args))
                out = {"result": func(**args)}
            except Exception as e:  # a bad tool call must not kill the turn
                log.warning("tool %s failed: %s", name, e)
                out = {"error": str(e)}
        return {"role": "tool", "tool_call_id": call["id"], "content": json.dumps(out, default=str)}

    def ask(self, user_input: str) -> str:
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_input})
        try:
            for _ in range(config.MAX_TOOL_ITERATIONS):
                data = self._post(
                    {
                        "model": self.model,
                        "messages": [{"role": "system", "content": gemini_brain._system_prompt()}, *self.messages],
                        "tools": self._tools,
                        "max_tokens": config.MAX_TOKENS,
                    }
                )
                msg = data["choices"][0]["message"]
                self.messages.append({k: v for k, v in msg.items() if v is not None})
                calls = msg.get("tool_calls")
                if not calls:
                    return (msg.get("content") or "").strip() or "Done."
                self.messages.extend(self._run_tool(c) for c in calls)
        except (KeyError, IndexError, ValueError) as e:
            self.messages = self.messages[:start]
            raise ProviderError(f"{self.name} sent a malformed response: {e}") from e
        except ProviderError:
            self.messages = self.messages[:start]
            raise
        return "That turned into a longer chain of steps than I could finish in one go."
