"""LLM provider interface and Ollama implementation.

A provider is a single callable: given messages, return the model's text.
The Ollama implementation asks for JSON output and strips any
``` fences some models wrap around JSON.
"""
from __future__ import annotations

import json
import re
from typing import Protocol

import httpx


class LlmProvider(Protocol):
    def complete(self, messages: list[dict], model: str) -> str:
        """Return the model's reply text for a chat-format message list."""
        ...


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


class OllamaProvider:
    def __init__(self, base_url: str, timeout: float = 300.0, client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=httpx.Timeout(timeout))

    def complete(self, messages: list[dict], model: str) -> str:
        resp = self._client.post(
            f"{self._base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.7},
            },
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]
