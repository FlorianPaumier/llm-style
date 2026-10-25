"""LLM provider interface and Ollama implementation.

A provider is a single callable: given messages, return the model's text.
The Ollama implementation asks for JSON output and strips any
``` fences some models wrap around JSON. extract_json pulls the first
object out of a reply (stylist); extract_json_multi pulls every object —
a top-level array stays a list, a lone object becomes a one-element
list (photo classification, where one photo may hold several items).
"""
from __future__ import annotations

import json
import re
from typing import Protocol

import httpx


class LlmProvider(Protocol):
    def complete(self, messages: list[dict], model: str, temperature: float = 0.7) -> str:
        """Return the model's reply text for a chat-format message list."""
        ...


def image_message(text: str, image_b64: str) -> dict:
    """Build an Ollama multimodal user message: text plus one base64 image."""
    return {
        "role": "user",
        "content": text,
        "images": [image_b64],
    }


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply.

    Small local models sometimes wrap JSON in ``` fences or add prose
    around it; find the first {...} block and parse it.
    """
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in reply")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("unbalanced JSON in reply")


def extract_json_multi(text: str) -> list[dict]:
    """Pull every JSON object out of a model reply, as a list of dicts.

    A top-level array `[...]` is bracket-matched whole and every element
    must be an object. A lone `{...}` (the single-item reply shape) is
    wrapped into a one-element list via extract_json, so replies in the
    old format keep working. Anything else raises ValueError.
    """
    fenced = _JSON_FENCE_RE.search(text)
    if fenced:
        text = fenced.group(1)
    stripped = text.lstrip()
    if not stripped.startswith("["):
        if not stripped.startswith("{"):
            raise ValueError("no JSON array or object in reply")
        return [extract_json(text)]
    start = text.find("[")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError as exc:
                    raise ValueError("unbalanced JSON in reply") from exc
                if not isinstance(parsed, list) \
                        or not all(isinstance(el, dict) for el in parsed):
                    raise ValueError("array elements must be objects")
                return parsed
    raise ValueError("unbalanced JSON in reply")


class OllamaProvider:
    def __init__(self, base_url: str, timeout: float = 300.0, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=httpx.Timeout(timeout))

    def complete(self, messages: list[dict], model: str, temperature: float = 0.7) -> str:
        resp = self._client.post(
            f"{self._base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": temperature},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
