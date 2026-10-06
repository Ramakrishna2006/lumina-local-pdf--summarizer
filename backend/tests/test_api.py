"""End-to-end API tests using the fake Ollama server from conftest.py."""

from __future__ import annotations

from pathlib import Path

from backend.tests.conftest import read_sse

DOC_A = (
    "Photosynthesis is the process plants use to convert sunlight into chemical energy. "
    "Chlorophyll in the chloroplast absorbs light. Oxygen is released as a by-product.\n\n" * 20
)
DOC_B = (
    "The French Revolution began in 1789. It ended the absolute monarchy and spread ideas "
    "of liberty, equality and fraternity across Europe.\n\n" * 20
)


def upload(client, name: str, text: str) -> dict:
    r = client.post("/api/documents/upload", files={"file": (name, text.encode(), "text/plain")})
    assert r.status_code == 200, r.text
    doc = client.get(f"/api/documents/{r.json()['id']}").json()
    assert doc["status"] == "completed", doc
    return doc


def test_health_config_models(client):
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["ollama_reachable"] is True
    config = client.get("/api/config").json()
    assert {s["id"] for s in config["answer_styles"]} >= {"concise", "detailed", "bullets"}
    models = client.get("/api/models").json()["models"]
    assert any(m["name"] == "fake-model" for m in models)


def test_upload_validation(client):
    assert client.post("/api/documents/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("empty.txt", b"", "text/plain")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("fake.pdf", b"not a pdf", "application/pdf")}).status_code == 400


def test_single_document_stream(client):
    doc = upload(client, "bio.txt", DOC_A)
    assert doc["rag"] is True
    r = client.post(f"/api/documents/{doc['id']}/ask/stream", json={"question": "What does chlorophyll do?", "style": "concise"})
    events = read_sse(r)
    types = [e["type"] for e in events]
    assert types[0] == "start" and types[-1] == "done"
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert sources and sources[0]["retrieval"] == "hybrid"
    answer = "".join(e["content"] for e in events if e["type"] == "token")
    assert "hello world" in answer
    assert "first_token_ms" in events[-1]["stats"]


def test_multi_document_chat_with_memory_and_regenerate(client, fake_ollama):
    a = upload(client, "a.txt", DOC_A)
    b = upload(client, "b.md", DOC_B)

    chat = client.post("/api/chats", json={"document_ids": [a["id"], b["id"]]}).json()
    assert set(chat["document_ids"]) == {a["id"], b["id"]}

    events = read_sse(client.post(f"/api/chats/{chat['id']}/messages/stream", json={"question": "Compare photosynthesis and the revolution"}))
    files = {s["filename"] for s in next(e for e in events if e["type"] == "sources")["sources"]}
    assert files == {"a.txt", "b.md"}, "both documents should contribute context"

    read_sse(client.post(f"/api/chats/{chat['id']}/messages/stream", json={"question": "why?"}))
    assert "CONVERSATION SO FAR" in fake_ollama.prompts[-1]["prompt"]

    full = client.get(f"/api/chats/{chat['id']}").json()
    assert [m["role"] for m in full["messages"]] == ["user", "assistant", "user", "assistant"]
    assert full["title"].startswith("Compare photosynthesis")

    read_sse(client.post(f"/api/chats/{chat['id']}/messages/stream", json={"regenerate": True}))
    again = client.get(f"/api/chats/{chat['id']}").json()
    assert [m["role"] for m in again["messages"]] == ["user", "assistant", "user", "assistant"]

    listed = client.get("/api/chats", params={"document_id": b["id"]}).json()
    assert any(c["id"] == chat["id"] for c in listed)

    export = client.get(f"/api/chats/{chat['id']}/export")
    assert export.status_code == 200 and "### You" in export.text

    renamed = client.patch(f"/api/chats/{chat['id']}", json={"title": "My notes"}).json()
    assert renamed["title"] == "My notes"


def test_summary_stream_and_download(client):
    doc = upload(client, "summary.txt", DOC_A)
    events = read_sse(client.post(f"/api/documents/{doc['id']}/summary/stream", json={"summary_type": "standard"}))
    assert events[-1]["type"] == "done"
    assert client.get(f"/api/documents/{doc['id']}/summary").json()["summary"]
    # second call is served from cache instantly
    cached = read_sse(client.post(f"/api/documents/{doc['id']}/summary/stream", json={}))
    assert cached[-1].get("cached") is True
    dl = client.get(f"/api/documents/{doc['id']}/summary/download?format=md")
    assert dl.status_code == 200 and "attachment" in dl.headers["content-disposition"]


def test_keyword_fallback_when_embeddings_missing(client, fake_ollama):
    from backend.app.services import rag_service

    fake_ollama.embed_fails = True
    try:
        doc = upload(client, "nofancy.txt", DOC_B)
        assert doc["rag"] is False
        rag_service.invalidate(doc["id"])
        r = client.post(f"/api/documents/{doc['id']}/ask", json={"question": "When did the French Revolution begin?"})
        assert r.status_code == 200, r.text
        assert r.json()["sources"][0]["retrieval"] == "keyword"
    finally:
        fake_ollama.embed_fails = False


def test_delete_removes_files_vectors_and_chats(client):
    from backend.app.core.config import settings

    doc = upload(client, "temp.txt", DOC_A)
    chat = client.post("/api/chats", json={"document_id": doc["id"]}).json()
    rag_files = list(Path(settings().rag_dir).glob(f"{doc['id']}.*"))
    assert rag_files

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert client.get(f"/api/chats/{chat['id']}").status_code == 404
    assert not any(p.exists() for p in rag_files)


def test_research_stream(client, monkeypatch):
    from backend.app import main
    from backend.app.services.web_research import ResearchSource

    async def fake_search(query, limit):
        return [ResearchSource("GitHub", "example/repo", "https://github.com/example/repo", "demo")]

    monkeypatch.setattr(main, "search_all", fake_search)
    events = read_sse(client.post("/api/research/stream", json={"question": "best local llm tools"}))
    assert next(e for e in events if e["type"] == "sources")["sources"][0]["url"].startswith("https://")
    assert events[-1]["type"] == "done"


def test_repeated_question_is_served_from_answer_cache(client, fake_ollama):
    doc = upload(client, "cache.txt", DOC_A)
    body = {"question": "What is released as a by-product?", "style": "concise"}
    first = read_sse(client.post(f"/api/documents/{doc['id']}/ask/stream", json=body))
    calls = len(fake_ollama.prompts)
    second = read_sse(client.post(f"/api/documents/{doc['id']}/ask/stream", json=body))
    assert len(fake_ollama.prompts) == calls, "cached answer must not call the model again"
    assert second[-1].get("cached") is True
    text = lambda ev: "".join(e["content"] for e in ev if e["type"] == "token").strip()  # noqa: E731
    assert text(first) == text(second)


def test_language_and_balanced_default(client, fake_ollama):
    doc = upload(client, "lang.txt", DOC_B)
    read_sse(client.post(f"/api/documents/{doc['id']}/ask/stream", json={"question": "When did it begin?", "language": "Hindi"}))
    system = fake_ollama.prompts[-1]["system"]
    assert "Hindi" in system and "direct answer" in system
    config = client.get("/api/config").json()
    assert config["default_style"] == "balanced"
    assert any(lang["id"] == "Tamil" for lang in config["languages"])
    assert any(t["id"] == "quiz" for t in config["summary_types"])


def test_suggestions_endpoint(client, fake_ollama):
    doc = upload(client, "suggest.txt", DOC_A)
    calls_before = len(fake_ollama.prompts)
    data = client.post("/api/suggestions", json={"document_ids": [doc["id"]]}).json()
    assert len(fake_ollama.prompts) == calls_before, "suggestions must not use the AI model"
    assert 2 <= len(data["suggestions"]) <= 4
    again = client.post("/api/suggestions", json={"document_ids": [doc["id"]]}).json()
    assert again["cached"] is True


def test_openai_compatible_provider(monkeypatch):
    """LLM_PROVIDER=openai streams from /v1/chat/completions (LM Studio, llama.cpp, vLLM...)."""
    import asyncio
    import json

    import httpx

    from backend.app.core.config import settings
    from backend.app.services import llm

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen2.5-7b-instruct"}]})
        body = json.loads(request.content)
        assert body["messages"][0]["role"] == "system"
        chunks = [{"choices": [{"delta": {"content": w}}]} for w in ["Hello", " from", " LM Studio"]]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, content=sse.encode())

    monkeypatch.setattr(settings(), "llm_provider", "openai")
    monkeypatch.setattr(llm, "_oa_client", httpx.AsyncClient(base_url="http://x/v1", transport=httpx.MockTransport(handler)))

    async def run():
        tokens = [t async for t in llm.generate_stream("hi", system="sys")]
        return "".join(tokens), await llm.list_models(), await llm.test_connection()

    text, models, ok = asyncio.run(run())
    assert text == "Hello from LM Studio"
    assert models[0]["name"] == "qwen2.5-7b-instruct" and ok


def test_delete_while_processing_stops_quietly(client):
    """Deleting a file while it is still being read must not log a failure."""
    from backend.app import main
    from backend.app.db.database import SessionLocal
    from backend.app.models.document import Document
    from backend.app.services import rag_service

    original = main.extract_document

    async def extract_then_user_deletes(path, file_type):
        result = await original(path, file_type)
        db = SessionLocal()
        try:
            doc = db.query(Document).filter(Document.stored_filename == Path(path).name).one()
            rag_service.cancel(doc.id)
            db.delete(doc)
            db.commit()
        finally:
            db.close()
        return result

    import logging

    records: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())

    handler = Collect(level=logging.INFO)
    logger = logging.getLogger("lumina")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    main.extract_document = extract_then_user_deletes
    try:
        r = client.post("/api/documents/upload", files={"file": ("gone.txt", DOC_A.encode(), "text/plain")})
        assert r.status_code == 200
        assert client.get(f"/api/documents/{r.json()['id']}").status_code == 404
        text = "\n".join(records)
        assert "Processing failed" not in text
        assert "deleted while it was being processed" in text
    finally:
        main.extract_document = original
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_background_indexing_waits_for_answers():
    """Smart-search indexing pauses while an answer is being written."""
    import asyncio

    from backend.app.services import rag_service

    async def scenario():
        rag_service.begin_answer()
        waiter = asyncio.create_task(rag_service._wait_while_answering())
        await asyncio.sleep(0.5)
        assert not waiter.done()
        rag_service.end_answer()
        await asyncio.wait_for(waiter, 2)

    asyncio.run(scenario())


def test_document_reports_search_mode(client):
    doc = upload(client, "mode.txt", DOC_B)
    assert doc["search"] in {"smart", "building", "keyword"}


def test_summary_question_uses_whole_document(client):
    doc = upload(client, "long.txt", "\n\n".join(f"Section {i}: topic number {i} is explained here. " * 12 for i in range(40)))
    r = client.post(f"/api/documents/{doc['id']}/ask/stream", json={"question": "give summary on this ppt"})
    events = read_sse(r)
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert sources and all(s["retrieval"] == "overview" for s in sources)
    parts = [s["chunk_index"] for s in sources]
    assert min(parts) == 0 and max(parts) >= 5, parts   # covers beginning AND later parts
    assert events[-1]["type"] == "done"


def test_slow_pc_keeps_full_answer_length(client, fake_ollama):
    """With a measured slow speed the answer keeps its full length; only the
    reading is focused so the first word comes sooner."""
    from backend.app.services import llm

    doc = upload(client, "speed.txt", DOC_A * 3)
    llm._speeds.clear()
    llm.record_speed("fake-model", {"prompt_eval_count": 400, "prompt_eval_duration": 10e9,
                                    "eval_count": 40, "eval_duration": 10e9})
    try:
        r = client.post(f"/api/documents/{doc['id']}/ask/stream", json={"question": "Why is oxygen released?"})
        events = read_sse(r)
        src = next(e for e in events if e["type"] == "sources")
        assert src["focused"] is True and src["first_word_s"] <= 20
        sent = fake_ollama.prompts[-1]
        assert sent["options"]["num_predict"] == 500
        assert "Keep the whole answer under" not in sent["prompt"]
        assert "STOP" not in "".join(e.get("content", "") for e in events if e["type"] == "token")
        health = client.get("/api/health").json()
        assert "fake-model" in health["speed"]["models"]
    finally:
        llm._speeds.clear()
