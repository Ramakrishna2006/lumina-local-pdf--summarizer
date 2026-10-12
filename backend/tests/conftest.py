"""Test setup: isolated temp storage + a fake Ollama server (no real model needed)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="lumina-test-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
    "UPLOAD_DIR": str(_TMP / "uploads"),
    "TEMP_DIR": str(_TMP / "tmp"),
    "SUMMARY_DIR": str(_TMP / "summaries"),
    "RAG_DIR": str(_TMP / "rag"),
    "LLM_WARMUP_ON_STARTUP": "false",
    "OLLAMA_MODEL": "fake-model",
    "RAG_EMBEDDING_MODEL": "fake-embed",
    "IMAGE_PRELOAD": "false",          # never download the real image model in tests
})

import httpx  # noqa: E402


class FakeOllama:
    """Minimal stand-in for the Ollama HTTP API."""

    def __init__(self) -> None:
        self.embed_fails = False
        self.prompts: list[dict] = []

    @staticmethod
    def vector(text: str, dims: int = 64) -> list[float]:
        vec = [0.0] * dims
        for word in text.lower().split():
            h = int(hashlib.md5(word.strip(".,!?").encode()).hexdigest(), 16)
            vec[h % dims] += 1.0
        return vec

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "fake-model", "size": 1, "details": {"parameter_size": "3B", "family": "llama"}},
                {"name": "fake-embed", "size": 1, "details": {"family": "nomic-bert"}},
            ]})
        body = json.loads(request.content or b"{}")
        if path == "/api/embed":
            if self.embed_fails:
                return httpx.Response(404, json={"error": "model not found"})
            inputs = body["input"] if isinstance(body["input"], list) else [body["input"]]
            return httpx.Response(200, json={"embeddings": [self.vector(t) for t in inputs]})
        if path == "/api/generate":
            self.prompts.append(body)
            if not body.get("prompt"):
                return httpx.Response(200, json={"done": True})
            words = ["**Answer:**", "the", "document", "says", "hello", "world."]
            if body.get("stream"):
                lines = [json.dumps({"response": w + " ", "done": False}) for w in words]
                lines.append(json.dumps({"response": "", "done": True}))
                return httpx.Response(200, content=("\n".join(lines) + "\n").encode())
            return httpx.Response(200, json={"response": " ".join(words), "done": True})
        return httpx.Response(404)


@pytest.fixture(scope="session")
def fake_ollama():
    return FakeOllama()


@pytest.fixture(scope="session")
def client(fake_ollama):
    from fastapi.testclient import TestClient

    from backend.app.core.config import settings
    from backend.app.main import app
    from backend.app.services import llm

    llm._client = httpx.AsyncClient(
        base_url=settings().ollama_base_url,
        transport=httpx.MockTransport(fake_ollama.handler),
    )
    with TestClient(app) as test_client:
        yield test_client


def read_sse(response) -> list[dict]:
    events = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events
