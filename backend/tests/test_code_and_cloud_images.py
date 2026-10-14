"""Code mode and the free online image service (pollinations) – no network needed."""

from __future__ import annotations

import io

import httpx
from PIL import Image

from backend.app.services import image_gen
from backend.tests.conftest import read_sse


def test_code_stream_answers_with_history(client, fake_ollama):
    history = [
        {"role": "user", "content": "Write a hello world in Python"},
        {"role": "assistant", "content": "```python\nprint('hello')\n```"},
    ]
    r = client.post("/api/code/stream", json={"question": "Now make it ask for a name", "history": history, "client_os": "windows"})
    assert r.status_code == 200, r.text
    events = read_sse(r)
    assert events[0]["type"] == "start" and events[0]["mode"] == "code"
    assert "".join(e["content"] for e in events if e["type"] == "token").strip()
    assert events[-1]["type"] == "done"
    sent = fake_ollama.prompts[-1]
    assert "PowerShell" in sent["system"] and "fenced" in sent["system"]
    assert "Write a hello world in Python" in sent["prompt"] and "ask for a name" in sent["prompt"]


def test_code_stream_validation(client):
    assert client.post("/api/code/stream", json={"question": ""}).status_code == 422
    assert client.post("/api/code/stream", json={"question": "x", "client_os": "dos"}).status_code == 422
    too_long = [{"role": "user", "content": "x"}] * 13
    assert client.post("/api/code/stream", json={"question": "x", "history": too_long}).status_code == 422


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "teal").save(buf, format="PNG")
    return buf.getvalue()


def test_pollinations_images(client, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    real = httpx.AsyncClient
    monkeypatch.setattr(image_gen.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(image_gen.settings(), "image_provider", "pollinations")

    st = client.get("/api/images/status").json()
    assert st["enabled"] and st["ready"] and st["hosted"] and st["provider"] == "pollinations"

    r = client.post("/api/images/generate", json={"prompt": "a red fox in snow", "seed": 5})
    assert r.status_code == 200, r.text
    assert "image.pollinations.ai/prompt/a%20red%20fox%20in%20snow" in seen["url"]
    assert "width=768" in seen["url"] and "seed=5" in seen["url"]
    assert client.get(r.json()["url"]).content[:8] == b"\x89PNG\r\n\x1a\n"


def test_pollinations_errors_are_clear(client, monkeypatch):
    responses = iter([
        httpx.Response(429, text="slow down"),
        httpx.Response(200, text="<html>not an image</html>", headers={"content-type": "text/html"}),
    ])
    real = httpx.AsyncClient
    monkeypatch.setattr(image_gen.httpx, "AsyncClient",
                        lambda **kw: real(transport=httpx.MockTransport(lambda req: next(responses)), **kw))
    monkeypatch.setattr(image_gen.settings(), "image_provider", "pollinations")
    busy = client.post("/api/images/generate", json={"prompt": "a cat"})
    assert busy.status_code == 429 and "busy" in busy.json()["detail"]
    wrong = client.post("/api/images/generate", json={"prompt": "a cat"})
    assert wrong.status_code == 502 and "did not return a picture" in wrong.json()["detail"]
