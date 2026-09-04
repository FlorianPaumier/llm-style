"""Tests for OllamaProvider plumbing and extract_json edge cases."""
import httpx

from app.llm.provider import OllamaProvider


def test_ollama_sends_chat_format_json_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = httpx.Request(
            request.method, request.url, content=request.content
        ).read()
        import json

        return httpx.Response(
            200,
            json={"message": {"content": '{"ok": true}'}},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = OllamaProvider("http://localhost:11434/", client=client)
    reply = provider.complete(
        [{"role": "user", "content": "hi"}], model="dolphin-mistral:7b"
    )
    assert reply == '{"ok": true}'
    assert captured["url"] == "http://localhost:11434/api/chat"
    import json

    body = json.loads(captured["body"])
    assert body["model"] == "dolphin-mistral:7b"
    assert body["format"] == "json"
    assert body["stream"] is False
    assert body["messages"] == [{"role": "user", "content": "hi"}]
