"""Lumina – private, local document AI (FastAPI backend).

Run from the project root:
    python -m uvicorn backend.app.main:app --reload --port 5001
Interactive API docs: http://127.0.0.1:5001/docs
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import mimetypes
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError, StaleDataError

from backend.app.core.config import settings
from backend.app.core.security import new_id, safe_filename, safe_original_filename, valid_pdf_signature
from backend.app.db.database import SessionLocal, get_db, init_db
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.chunk import DocumentChunk
from backend.app.models.document import Document
from backend.app.services import answer_cache
from backend.app.services import chat as chat_service
from backend.app.services import image_gen
from backend.app.services import rag_service
from backend.app.services.extraction.pdf import engine_name as pdf_engine
from backend.app.services.extraction.extractor import extract_document, supported_extensions
from backend.app.services.indexer import index_document
from backend.app.services.llm import (
    ANSWER_LANGUAGES,
    ANSWER_STYLES,
    STOP_NOTE,
    answer_budget,
    close_client,
    generate,
    generate_answer,
    generate_answer_stream,
    list_models,
    measure_speed,
    normalize_language,
    normalize_style,
    resolve_model,
    speed_report,
    within_time,
    test_connection,
    warmup,
)
from backend.app.services.suggest import quick_suggestions
from backend.app.services.summary import SUMMARY_LABELS, SUMMARY_TYPES, generate_summary, stream_summary
from backend.app.services.web_research import platforms, research_question, search_all, stream_research

s = settings()

logging.basicConfig(
    level=getattr(logging, s.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("lumina")

STAGE_PROGRESS = {
    "queued": 5, "starting": 10, "extracting": 40, "indexing": 75,
    "rag_indexing": 80, "completed": 100, "summarizing": 100,
    "summary_failed": 100, "failed": 100,
}


# ============================================================
# APP LIFECYCLE
# ============================================================

async def _warm_models() -> None:
    if not s.llm_warmup_on_startup:
        return
    await warmup()
    await measure_speed()          # learn how fast this PC runs the model
    if s.rag_enabled:
        try:
            await rag_service.embed("warm up")
        except Exception as exc:  # noqa: BLE001
            log.warning("Embedding warm-up skipped: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    log.info(
        "%s v%s starting – provider=%s model=%s embeddings=%s pdf=%s",
        s.app_name, s.app_version, s.provider, s.default_model, s.embedding_model or "keyword-only", pdf_engine(),
    )
    warm_task = asyncio.create_task(_warm_models())
    yield
    warm_task.cancel()
    await close_client()


app = FastAPI(
    title=s.app_name,
    version=s.app_version,
    description="Private, local document summarization and question answering powered by Ollama "
    "or any OpenAI-compatible local model server.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=2048)


# ============================================================
# ACCESS PASSWORD (only when ACCESS_PASSWORD is set in .env)
# ============================================================

ACCESS_COOKIE = "lumina_access"
_OPEN_PATHS = {"/api/auth/status", "/api/auth/login", "/api/auth/logout"}


def _access_token() -> str:
    """Cookie value derived from the password (the password itself is never sent back)."""
    return hmac.new(s.access_password.encode(), b"lumina-access-v1", hashlib.sha256).hexdigest()


def _has_access(request: Request) -> bool:
    if not s.access_password:
        return True
    return hmac.compare_digest(request.cookies.get(ACCESS_COOKIE, ""), _access_token())


@app.middleware("http")
async def access_guard(request: Request, call_next):
    path = request.url.path
    protected = path.startswith("/api") or path in {"/docs", "/redoc", "/openapi.json"}
    if protected and path not in _OPEN_PATHS and request.method != "OPTIONS" and not _has_access(request):
        return JSONResponse({"detail": "Password required."}, status_code=401)
    return await call_next(request)


class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=200)


@app.get("/api/auth/status")
def auth_status(request: Request):
    return {"required": bool(s.access_password), "ok": _has_access(request)}


@app.post("/api/auth/login")
async def auth_login(body: LoginRequest, request: Request):
    if not s.access_password:
        return {"ok": True}
    if not hmac.compare_digest(body.password.encode(), s.access_password.encode()):
        await asyncio.sleep(1.0)  # slow down password guessing
        raise HTTPException(401, "Wrong password.")
    secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response = JSONResponse({"ok": True})
    response.set_cookie(
        ACCESS_COOKIE, _access_token(), max_age=30 * 24 * 3600,
        httponly=True, samesite="lax", secure=secure, path="/",
    )
    return response


@app.post("/api/auth/logout")
def auth_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(ACCESS_COOKIE, path="/")
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if "cache-control" not in response.headers:
        response.headers["Cache-Control"] = "no-store"
    return response


# ============================================================
# REQUEST MODELS
# ============================================================

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000)
    style: str | None = None
    model: str | None = None
    language: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=12)


class MultiAskRequest(AskRequest):
    document_ids: list[str] = Field(..., min_length=1, max_length=30)


class ChatCreateRequest(BaseModel):
    document_id: str | None = Field(default=None, max_length=100)
    document_ids: list[str] | None = Field(default=None, max_length=30)
    title: str = Field(default="New Chat", max_length=200)


class ChatRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class ChatMessageRequest(BaseModel):
    question: str | None = Field(default=None, max_length=5000)
    content: str | None = Field(default=None, max_length=5000)  # older frontend field name
    style: str | None = None
    model: str | None = None
    language: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=12)
    regenerate: bool = False


class SummaryRequest(BaseModel):
    summary_type: str = "standard"
    model: str | None = None
    language: str | None = None
    regenerate: bool = False


class ResearchRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    document_id: str | None = None
    document_ids: list[str] = Field(default_factory=list, max_length=30)
    chat_id: str | None = None
    model: str | None = None
    language: str | None = None


class SuggestRequest(BaseModel):
    document_ids: list[str] = Field(..., min_length=1, max_length=30)
    model: str | None = None


# ============================================================
# HELPERS
# ============================================================

def sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


def sse_response(generator: AsyncGenerator[str, None]) -> StreamingResponse:
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


def iso(value) -> str | None:
    return value.isoformat() if value else None


def get_document_or_404(db: Session, document_id: str) -> Document:
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def document_json(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "mime_type": doc.mime_type,
        "size": doc.size,
        "status": doc.status,
        "stage": doc.stage,
        "progress": STAGE_PROGRESS.get(doc.stage or "", 50),
        "ocr_used": doc.ocr_used,
        "page_count": doc.page_count,
        "extracted_chars": doc.extracted_chars,
        "has_summary": bool(doc.summary),
        "summary": doc.summary,
        "rag": rag_service.rag_index_exists(doc.id),
        "search": (
            "smart" if rag_service.rag_index_exists(doc.id)
            else "building" if rag_service.is_building(doc.id)
            else "keyword"
        ),
        "error": doc.error,
        "created_at": iso(doc.created_at),
        "updated_at": iso(doc.updated_at),
    }


def chat_json(db: Session, chat: ChatSession, with_messages: bool = False) -> dict[str, Any]:
    data = {
        "id": chat.id,
        "document_id": chat.document_id,
        "document_ids": chat_service.chat_document_ids(chat),
        "title": chat.title,
        "created_at": iso(chat.created_at),
        "updated_at": iso(chat.updated_at),
    }
    if with_messages:
        data["messages"] = [
            {"id": m.id, "role": m.role, "content": m.content, "sources": m.sources, "created_at": iso(m.created_at)}
            for m in chat_service.get_messages(db, chat.id)
        ]
    else:
        data["message_count"] = db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).count()
    return data


def retrieval_query(question: str, history: list[dict[str, str]]) -> str:
    """Short follow-ups ("explain more", "why?") reuse the previous question for retrieval."""
    if len(question.split()) <= 6:
        previous = [h["content"] for h in history if h.get("role") == "user"]
        if previous:
            return f"{previous[-1]} {question}"
    return question


async def stream_answer(
    *,
    question: str,
    document_ids: list[str],
    style: str | None,
    model: str | None,
    top_k: int | None,
    history: list[dict[str, str]] | None = None,
    on_complete=None,
    language: str | None = None,
    use_cache: bool = True,
) -> AsyncGenerator[str, None]:
    """Shared SSE pipeline: (cache) -> retrieve ONCE -> sources -> stream tokens -> done."""
    started = time.perf_counter()
    first_token_at: float | None = None
    answer = ""
    model_name, style_name, lang = resolve_model(model), normalize_style(style), normalize_language(language)
    yield sse({"type": "start", "document_count": len(document_ids), "model": model_name, "style": style_name})

    cache_key = answer_cache.make_key(
        question=question, document_ids=document_ids, style=style_name,
        model=model_name, language=lang, history=history,
    )
    cached = answer_cache.get(cache_key) if use_cache else None
    if cached is not None:
        # Instant answer: same question, same documents, same settings.
        yield sse({"type": "sources", "sources": cached.sources, "retrieval_ms": 0})
        yield sse({"type": "token", "content": cached.answer})
        if on_complete is not None:
            on_complete(cached.answer, cached.sources)
        ms = int((time.perf_counter() - started) * 1000)
        yield sse({"type": "done", "cached": True, "stats": {
            "retrieval_ms": 0, "first_token_ms": ms, "total_ms": ms, "chars": len(cached.answer), "cached": True,
        }})
        return

    db = SessionLocal()
    rag_service.begin_answer()              # background indexing pauses while we answer
    try:
        # Plan for THIS computer: the answer keeps its full length; on a slow CPU
        # the model reads fewer, focused passages so the first word comes sooner.
        n_hist = min(len(history or []), s.chat_history_messages)
        plan = answer_budget(
            model_name, ANSWER_STYLES[style_name]["max_tokens"],
            extra_chars=len(question) + 260 * n_hist,
        )
        if rag_service.wants_overview(question):
            # "Summarize this ppt" -> excerpts from the whole document, start to end.
            context, sources = rag_service.overview_context(db, document_ids, plan["context_chars"])
        else:
            context, sources = await rag_service.retrieve_multi_rag_context(
                db, document_ids, retrieval_query(question, history or []), top_k, plan["context_chars"]
            )
        retrieval_ms = int((time.perf_counter() - started) * 1000)
        yield sse({
            "type": "sources", "sources": sources, "retrieval_ms": retrieval_ms,
            "estimate_s": plan["est_seconds"], "first_word_s": plan.get("first_word_seconds"),
            "focused": plan["adapted"],
        })

        async for token in within_time(generate_answer_stream(
            question, context, style=style, history=history, model=model, language=language,
            max_tokens=plan["max_tokens"],
        ), started):
            if first_token_at is None:
                first_token_at = time.perf_counter()
            answer += token
            yield sse({"type": "token", "content": token})

        answer = answer.strip() or "I could not find that information in the selected document(s)."
        if on_complete is not None:
            on_complete(answer, sources)
        if STOP_NOTE not in answer:          # never cache an answer that was cut short
            answer_cache.put(cache_key, answer, sources, document_ids)

        total = time.perf_counter() - started
        yield sse({
            "type": "done",
            "stats": {
                "retrieval_ms": retrieval_ms,
                "first_token_ms": int(((first_token_at or time.perf_counter()) - started) * 1000),
                "total_ms": int(total * 1000),
                "chars": len(answer),
            },
        })
    except Exception as exc:  # noqa: BLE001
        log.exception("Streaming answer failed")
        yield sse({"type": "error", "message": str(exc)})
    finally:
        rag_service.end_answer()
        db.close()


# ============================================================
# SYSTEM
# ============================================================

@app.get("/api")
def api_root():
    return {"name": s.app_name, "version": s.app_version, "status": "running", "docs": "/docs"}


@app.get("/api/health")
async def health():
    reachable = await test_connection()
    return {
        "status": "ok",
        "version": s.app_version,
        "llm_provider": s.provider,
        "ollama_reachable": reachable,  # kept for older frontends
        "llm_reachable": reachable,
        "ollama_model": s.default_model,
        "default_model": s.default_model,
        "rag_enabled": s.rag_enabled,
        "rag_embedding_model": s.embedding_model,
        "pdf_engine": pdf_engine(),
        "answer_cache": answer_cache.stats(),
        "speed": speed_report(),
        "web_research_enabled": s.web_research_enabled,
        "google_custom_search_configured": s.google_search_configured,
        "supported_file_types": sorted(supported_extensions()),
    }


@app.get("/api/models")
async def models():
    available = await list_models()
    return {"default": s.default_model, "embedding_model": s.embedding_model, "models": available}


@app.get("/api/config")
def config():
    return {
        "app_name": s.app_name,
        "version": s.app_version,
        "max_file_size_mb": s.max_file_size_mb,
        "supported_file_types": sorted(supported_extensions()),
        "answer_styles": [{"id": k, "label": v["label"]} for k, v in ANSWER_STYLES.items()],
        "summary_types": [{"id": k, "label": SUMMARY_LABELS.get(k, k.title())} for k in SUMMARY_TYPES],
        "languages": [{"id": k, "label": v} for k, v in ANSWER_LANGUAGES.items()],
        "default_style": normalize_style(None),
        "default_model": s.default_model,
        "llm_provider": s.provider,
        "web_research_enabled": s.web_research_enabled,
        "search_platforms": platforms(),
    }


# ============================================================
# DOCUMENT PROCESSING (background)
# ============================================================

async def process(document_id: str) -> None:
    """Upload -> extract (thread, parallel OCR) -> chunk -> READY.

    The document is usable as soon as its text is chunked (keyword search).
    The slower semantic "smart search" index is then built in the background,
    one document at a time, so several uploads never slow each other down.
    """
    db = SessionLocal()
    started = time.perf_counter()

    def deleted() -> bool:
        if rag_service.is_cancelled(document_id):
            log.info("Document %s was deleted while it was being processed – stopped.", document_id)
            if stored_name:
                _remove_file(Path(s.upload_dir) / stored_name)   # in case Windows kept it open before
            return True
        return False

    stored_name = ""

    try:
        document = db.get(Document, document_id)
        if document is None:
            return

        def stage(name: str) -> None:
            document.stage = name
            db.commit()

        document.status, document.error = "processing", None
        stage("starting")

        stored_name = document.stored_filename
        upload_path = Path(s.upload_dir) / stored_name
        if not upload_path.exists():
            raise RuntimeError("Stored document file no longer exists.")

        stage("extracting")
        extraction = await extract_document(upload_path, document.file_type)
        if deleted():
            return
        text = (extraction.text or "").strip()
        if len(text) < 20:
            raise RuntimeError("No readable text could be extracted from this file.")

        document.extracted_text = text
        document.extracted_chars = len(text)
        document.page_count = extraction.page_count
        document.ocr_used = extraction.ocr_used
        document.summary = None
        stage("indexing")

        chunk_count = await asyncio.to_thread(_index_in_thread, document_id, text)
        if deleted():
            return
        rag_service.delete_index(document_id)       # old vectors no longer match the new chunks
        answer_cache.invalidate_document(document_id)
        _suggestion_cache.clear()

        document.status, document.error = "completed", None
        stage("completed")
        log.info("Document %s ready in %.1fs (%d chunks)", document_id, time.perf_counter() - started, chunk_count)

        if s.rag_enabled:
            rag_service.schedule_background_index(document_id)

        if s.delete_source_after_processing:
            upload_path.unlink(missing_ok=True)

    except (StaleDataError, ObjectDeletedError):
        db.rollback()
        log.info("Document %s was deleted while it was being processed – stopped.", document_id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        document = db.get(Document, document_id)
        if document is None:
            log.info("Document %s was deleted while it was being processed – stopped.", document_id)
            return
        if deleted():
            return
        log.exception("Processing failed for %s", document_id)
        document.status = "failed"
        document.stage = "failed"
        document.error = str(exc)[:300]
        db.commit()
    finally:
        db.close()


def _remove_file(path: Path) -> bool:
    """Delete a file; on Windows a file that is still open cannot be deleted,
    so that case is logged and retried when processing of it stops."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        log.info("Could not delete %s yet (%s) – it will be removed after processing.", path.name, exc)
        return False


def _index_in_thread(document_id: str, text: str) -> int:
    db = SessionLocal()
    try:
        return index_document(db, document_id, text)
    finally:
        db.close()


async def _save_upload(upload: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as output:
        while data := await upload.read(1024 * 1024):
            total += len(data)
            if total > s.max_file_size_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds the maximum size of {s.max_file_size_mb} MB.")
            output.write(data)
    return total


# ============================================================
# DOCUMENTS
# ============================================================

@app.post("/api/documents/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename:
        raise HTTPException(400, "Filename is required.")

    original = safe_original_filename(file.filename)
    extension = Path(original).suffix.lower()
    if extension not in supported_extensions():
        raise HTTPException(400, f"Unsupported file type: {extension or 'none'}. Supported: {', '.join(sorted(supported_extensions()))}")

    document_id = new_id()
    stored = safe_filename(document_id, extension)
    destination = Path(s.upload_dir) / stored

    try:
        size = await _save_upload(file, destination)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        destination.unlink(missing_ok=True)
        log.exception("Could not save upload")
        raise HTTPException(500, "Could not save uploaded file.") from exc

    if size == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is empty.")

    if extension == ".pdf":
        # Read the header and CLOSE the file before deleting it – Windows cannot
        # delete a file that is still open.
        with destination.open("rb") as f:
            header = f.read(5)
        if not valid_pdf_signature(header):
            destination.unlink(missing_ok=True)
            raise HTTPException(400, "Invalid PDF file.")

    document = Document(
        id=document_id,
        filename=original,
        stored_filename=stored,
        file_type=extension.lstrip("."),
        mime_type=mimetypes.guess_type(original)[0] or "application/octet-stream",
        size=size,
        status="queued",
        stage="queued",
    )
    db.add(document)
    db.commit()

    background_tasks.add_task(process, document_id)
    return {**document_json(document), "message": "Upload successful. Processing started."}


@app.get("/api/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return [document_json(d) for d in docs]


@app.get("/api/documents/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    return document_json(get_document_or_404(db, document_id))


@app.get("/api/documents/{document_id}/preview")
def preview_document(document_id: str, limit: int = 6000, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    text = doc.extracted_text or ""
    limit = max(500, min(limit, 50000))
    return {"document_id": doc.id, "filename": doc.filename, "text": text[:limit], "truncated": len(text) > limit, "total_chars": len(text)}


@app.post("/api/documents/{document_id}/retry")
def retry(document_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    if doc.status == "processing":
        return {"status": "processing", "message": "Document is already being processed."}
    doc.status, doc.stage, doc.error = "queued", "queued", None
    db.commit()
    background_tasks.add_task(process, document_id)
    return {"status": "queued", "message": "Processing restarted.", "document_id": document_id}


@app.post("/api/documents/{document_id}/rag/reindex")
async def reindex_document_rag(document_id: str, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    if doc.status != "completed":
        raise HTTPException(409, f"Document is not ready. Current status: {doc.status}")
    answer_cache.invalidate_document(document_id)
    try:
        return {"status": "completed", "rag": await rag_service.index_document_rag(document_id, db)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"RAG indexing failed: {exc}") from exc


@app.get("/api/documents/{document_id}/download")
def download_document(document_id: str, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    path = Path(s.upload_dir) / doc.stored_filename
    if not path.exists():
        raise HTTPException(404, "Original file is no longer available.")
    return FileResponse(path=str(path), filename=doc.filename, media_type=doc.mime_type)


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    stored_path = Path(s.upload_dir) / doc.stored_filename
    try:
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete(synchronize_session=False)
        for chat in db.query(ChatSession).all():
            ids = chat_service.chat_document_ids(chat)
            if document_id not in ids:
                continue
            remaining = [i for i in ids if i != document_id]
            if remaining:
                chat.document_ids, chat.document_id = remaining, remaining[0]
            else:
                db.query(ChatMessage).filter(ChatMessage.chat_id == chat.id).delete(synchronize_session=False)
                db.delete(chat)
        db.delete(doc)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Could not delete document")
        raise HTTPException(500, "Could not delete document.") from exc

    _remove_file(stored_path)               # Windows: busy files are removed after reading stops
    rag_service.cancel(document_id)         # stops background indexing + deletes vectors
    answer_cache.invalidate_document(document_id)
    _suggestion_cache.clear()
    return {"status": "deleted", "document_id": document_id}


# ============================================================
# SUMMARIES
# ============================================================

async def _background_summary(document_id: str, summary_type: str = "standard", model: str | None = None) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        if doc is None or not doc.extracted_text:
            return
        doc.stage = "summarizing"
        db.commit()
        doc.summary = await generate_summary(doc.extracted_text, summary_type, model)
        doc.stage, doc.error = "completed", None
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Summary failed for %s", document_id)
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.stage, doc.error = "summary_failed", str(exc)[:300]
            db.commit()
    finally:
        db.close()


@app.post("/api/documents/{document_id}/summarize")
def summarize_document(document_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    if doc.status != "completed" or not doc.extracted_text:
        raise HTTPException(409, "Document must finish processing before it can be summarized.")
    if doc.summary:
        return {"status": "completed", "document_id": document_id, "summary": doc.summary}
    if doc.stage == "summarizing":
        return {"status": "processing", "document_id": document_id}
    doc.stage = "summarizing"
    db.commit()
    background_tasks.add_task(_background_summary, document_id)
    return {"status": "processing", "message": "Summary generation started.", "document_id": document_id}


@app.post("/api/documents/{document_id}/summary/stream")
async def summary_stream(document_id: str, request: SummaryRequest):
    """Stream a summary token-by-token (much faster perceived speed)."""
    db = SessionLocal()
    try:
        doc = get_document_or_404(db, document_id)
        if doc.status != "completed" or not doc.extracted_text:
            raise HTTPException(409, "Document must finish processing before it can be summarized.")
        text = doc.extracted_text
        language = normalize_language(request.language)
        is_default = request.summary_type == "standard" and language == "auto"
        cached = doc.summary if (doc.summary and not request.regenerate and is_default) else None
    finally:
        db.close()

    async def events():
        started = time.perf_counter()
        yield sse({"type": "start", "summary_type": request.summary_type})
        if cached:
            yield sse({"type": "token", "content": cached})
            yield sse({"type": "done", "cached": True, "stats": {"total_ms": 0}})
            return
        summary = ""
        first = None
        try:
            with rag_service.answer_priority():
                async for token in within_time(stream_summary(text, request.summary_type, request.model, language), started):
                    first = first or time.perf_counter()
                    summary += token
                    yield sse({"type": "token", "content": token})
            save_db = SessionLocal()
            try:
                doc2 = save_db.get(Document, document_id)
                if doc2 is not None and is_default:
                    doc2.summary, doc2.stage, doc2.error = summary.strip(), "completed", None
                    save_db.commit()
            finally:
                save_db.close()
            yield sse({"type": "done", "stats": {
                "first_token_ms": int(((first or time.perf_counter()) - started) * 1000),
                "total_ms": int((time.perf_counter() - started) * 1000),
            }})
        except Exception as exc:  # noqa: BLE001
            log.exception("Summary stream failed")
            yield sse({"type": "error", "message": str(exc)})

    return sse_response(events())


@app.get("/api/documents/{document_id}/summary")
def get_summary(document_id: str, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    if doc.summary:
        return {"document_id": doc.id, "filename": doc.filename, "summary": doc.summary, "status": "completed"}
    if doc.stage == "summarizing":
        raise HTTPException(409, "Summary is still being generated.")
    if doc.stage == "summary_failed":
        raise HTTPException(500, doc.error or "Summary generation failed.")
    raise HTTPException(404, "Summary is not available yet.")


@app.get("/api/documents/{document_id}/status")
def get_status(document_id: str, db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    return {"id": doc.id, "status": doc.status, "stage": doc.stage, "progress": STAGE_PROGRESS.get(doc.stage or "", 50), "error": doc.error}


@app.get("/api/documents/{document_id}/summary/download")
def download_summary(document_id: str, format: str = "md", db: Session = Depends(get_db)):
    doc = get_document_or_404(db, document_id)
    if not doc.summary:
        raise HTTPException(404, "Generate a summary first.")
    ext = "md" if format == "md" else "txt"
    name = f"{Path(doc.filename).stem}-summary.{ext}"
    body = f"# Summary of {doc.filename}\n\n{doc.summary}\n" if ext == "md" else doc.summary
    return PlainTextResponse(body, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ============================================================
# QUESTION ANSWERING (stateless)
# ============================================================

@app.post("/api/documents/{document_id}/ask")
async def ask_document(document_id: str, request: AskRequest, db: Session = Depends(get_db)):
    get_document_or_404(db, document_id)
    return await _ask([document_id], request, db)


@app.post("/api/multi-document/ask")
async def ask_multiple_documents(request: MultiAskRequest, db: Session = Depends(get_db)):
    return await _ask(request.document_ids, request, db)


async def _ask(document_ids: list[str], request: AskRequest, db: Session) -> dict[str, Any]:
    try:
        context, sources = await rag_service.retrieve_multi_rag_context(db, document_ids, request.question, request.top_k)
        answer = await generate_answer(
            request.question, context, style=request.style, model=request.model, language=request.language
        )
        return {"answer": answer, "sources": sources, "document_ids": document_ids}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Question answering failed")
        raise HTTPException(500, f"Question answering failed: {exc}") from exc


@app.post("/api/documents/{document_id}/ask/stream")
async def ask_document_stream(document_id: str, request: AskRequest):
    return sse_response(stream_answer(
        question=request.question, document_ids=[document_id],
        style=request.style, model=request.model, top_k=request.top_k, language=request.language,
    ))


@app.post("/api/multi-document/ask/stream")
async def ask_multiple_documents_stream(request: MultiAskRequest):
    return sse_response(stream_answer(
        question=request.question, document_ids=request.document_ids,
        style=request.style, model=request.model, top_k=request.top_k, language=request.language,
    ))


# ============================================================
# CHATS
# ============================================================

@app.post("/api/chats")
def create_chat_endpoint(request: ChatCreateRequest, db: Session = Depends(get_db)):
    try:
        chat = chat_service.create_chat(db, request.document_id, request.title, request.document_ids)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    return chat_json(db, chat)


@app.get("/api/chats")
def get_chats(document_id: str | None = None, db: Session = Depends(get_db)):
    return [chat_json(db, c) for c in chat_service.list_chats(db, document_id)]


@app.get("/api/chats/{chat_id}")
def get_chat_endpoint(chat_id: str, db: Session = Depends(get_db)):
    chat = chat_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found.")
    return chat_json(db, chat, with_messages=True)


@app.patch("/api/chats/{chat_id}")
def rename_chat_endpoint(chat_id: str, request: ChatRenameRequest, db: Session = Depends(get_db)):
    try:
        return chat_json(db, chat_service.rename_chat(db, chat_id, request.title))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.delete("/api/chats/{chat_id}")
def delete_chat_endpoint(chat_id: str, db: Session = Depends(get_db)):
    if chat_service.get_chat(db, chat_id) is None:
        raise HTTPException(404, "Chat not found.")
    chat_service.delete_chat(db, chat_id)
    return {"status": "deleted", "chat_id": chat_id}


@app.get("/api/chats/{chat_id}/export")
def export_chat(chat_id: str, db: Session = Depends(get_db)):
    chat = chat_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found.")
    safe = "".join(c for c in chat.title if c.isalnum() or c in " -_")[:50].strip() or "chat"
    return PlainTextResponse(
        chat_service.export_markdown(db, chat),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


def _prepare_chat_turn(db: Session, chat_id: str, request: ChatMessageRequest) -> tuple[ChatSession, str, list[dict[str, str]]]:
    chat = chat_service.get_chat(db, chat_id)
    if chat is None:
        raise HTTPException(404, "Chat not found.")
    doc_ids = chat_service.chat_document_ids(chat)
    for doc_id in doc_ids:
        doc = db.get(Document, doc_id)
        if doc is None:
            raise HTTPException(404, "A document in this chat no longer exists.")
        if doc.status != "completed":
            raise HTTPException(409, f"'{doc.filename}' is not ready yet (status: {doc.status}).")

    if request.regenerate:
        messages = chat_service.get_messages(db, chat_id)
        last_user = next((m for m in reversed(messages) if m.role == "user"), None)
        if last_user is None:
            raise HTTPException(400, "Nothing to regenerate.")
        for m in messages:
            if m.created_at >= last_user.created_at and m.id != last_user.id and m.role == "assistant":
                db.delete(m)
        db.commit()
        question = last_user.content
        history = [h for h in chat_service.recent_history(db, chat_id, s.chat_history_messages + 1)][:-1]
    else:
        question = (request.question or request.content or "").strip()
        if not question:
            raise HTTPException(400, "Message cannot be empty.")
        history = chat_service.recent_history(db, chat_id, s.chat_history_messages)
        chat_service.add_message(db, chat_id, "user", question)
    return chat, question, history


@app.post("/api/chats/{chat_id}/messages")
async def send_chat_message(chat_id: str, request: ChatMessageRequest, db: Session = Depends(get_db)):
    chat, question, history = _prepare_chat_turn(db, chat_id, request)
    try:
        context, sources = await rag_service.retrieve_multi_rag_context(
            db, chat_service.chat_document_ids(chat), retrieval_query(question, history), request.top_k
        )
        answer = await generate_answer(
            question, context, style=request.style, history=history, model=request.model, language=request.language
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        log.exception("Chat message failed")
        raise HTTPException(500, f"Could not generate a response: {exc}") from exc
    message = chat_service.add_message(db, chat_id, "assistant", answer, sources)
    return {"chat_id": chat_id, "question": question, "answer": answer, "sources": sources, "message_id": message.id}


@app.post("/api/chats/{chat_id}/messages/stream")
async def stream_chat_message(chat_id: str, request: ChatMessageRequest):
    db = SessionLocal()
    try:
        chat, question, history = _prepare_chat_turn(db, chat_id, request)
        document_ids = chat_service.chat_document_ids(chat)
    finally:
        db.close()

    def save(answer: str, sources: list[dict[str, Any]]) -> None:
        save_db = SessionLocal()
        try:
            chat_service.add_message(save_db, chat_id, "assistant", answer, sources)
        finally:
            save_db.close()

    return sse_response(stream_answer(
        question=question, document_ids=document_ids, style=request.style,
        model=request.model, top_k=request.top_k, history=history, on_complete=save,
        language=request.language, use_cache=not request.regenerate,
    ))


# ============================================================
# IMAGE GENERATION ("Image" mode)
# ============================================================

class ImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    size: int | None = Field(default=None, ge=256, le=1024)
    steps: int | None = Field(default=None, ge=1, le=50)
    seed: int | None = Field(default=None, ge=0, le=2**31 - 1)


@app.get("/api/images/status")
def image_status():
    return image_gen.status()


@app.post("/api/images/generate")
async def generate_image(request: ImageRequest):
    try:
        return await image_gen.generate(request.prompt, request.size, request.steps, request.seed)
    except image_gen.ImageError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@app.get("/api/images/{image_id}")
def get_image(image_id: str):
    path = image_gen.image_path(image_id)
    if path is None:
        raise HTTPException(404, "Image not found.")
    return FileResponse(
        path, media_type="image/png", filename=f"lumina-{image_id[:8]}.png", content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ============================================================
# WEB RESEARCH
# ============================================================

def _research_doc_ids(request: ResearchRequest) -> list[str]:
    ids = list(dict.fromkeys(i.strip() for i in request.document_ids if i and i.strip()))
    if request.document_id and request.document_id not in ids:
        ids.insert(0, request.document_id)
    return ids


async def _research_context(doc_ids: list[str], question: str) -> str:
    if not doc_ids:
        return ""
    db = SessionLocal()
    try:
        context, _ = await rag_service.retrieve_multi_rag_context(db, doc_ids, question, 6, 5000)
        return context
    except Exception as exc:  # noqa: BLE001
        log.warning("Document context for research skipped: %s", exc)
        return ""
    finally:
        db.close()


@app.post("/api/research")
async def web_research(request: ResearchRequest):
    if not s.web_research_enabled:
        raise HTTPException(403, "Web research is disabled in .env (WEB_RESEARCH_ENABLED=false).")
    context = await _research_context(_research_doc_ids(request), request.question)
    try:
        return await research_question(request.question, context, 5, model=request.model)
    except Exception as exc:  # noqa: BLE001
        log.exception("Web research failed")
        raise HTTPException(502, f"Web research failed: {exc}") from exc


@app.post("/api/research/stream")
async def web_research_stream(request: ResearchRequest):
    if not s.web_research_enabled:
        raise HTTPException(403, "Web research is disabled in .env (WEB_RESEARCH_ENABLED=false).")

    if request.chat_id:
        db = SessionLocal()
        try:
            if chat_service.get_chat(db, request.chat_id) is None:
                raise HTTPException(404, "Chat not found.")
            chat_service.add_message(db, request.chat_id, "user", request.question)
        finally:
            db.close()

    async def events():
        started = time.perf_counter()
        yield sse({"type": "start", "mode": "web"})
        try:
            context_task = asyncio.create_task(_research_context(_research_doc_ids(request), request.question))
            found = await search_all(request.question, 5)
            context = await context_task
            sources = [
                {"rank": i, "source": x.source, "title": x.title, "url": x.url, "snippet": x.snippet}
                for i, x in enumerate(found, start=1)
            ]
            yield sse({"type": "sources", "sources": sources, "retrieval_ms": int((time.perf_counter() - started) * 1000)})
            answer = ""
            first = None
            async for token in within_time(stream_research(request.question, found, context, request.model, request.language), started):
                first = first or time.perf_counter()
                answer += token
                yield sse({"type": "token", "content": token})
            if request.chat_id and answer.strip():
                save_db = SessionLocal()
                try:
                    chat_service.add_message(save_db, request.chat_id, "assistant", answer.strip(), sources)
                finally:
                    save_db.close()
            yield sse({"type": "done", "stats": {
                "first_token_ms": int(((first or time.perf_counter()) - started) * 1000),
                "total_ms": int((time.perf_counter() - started) * 1000),
            }})
        except Exception as exc:  # noqa: BLE001
            log.exception("Research stream failed")
            yield sse({"type": "error", "message": str(exc)})

    return sse_response(events())


# ============================================================
# SUGGESTED QUESTIONS
# ============================================================

_suggestion_cache: dict[tuple[str, ...], list[str]] = {}

FALLBACK_SUGGESTIONS = [
    "Summarize the main ideas in five bullet points",
    "What are the key definitions I should know?",
    "List every important date, number and name",
    "Make three exam questions from this material",
]


@app.post("/api/suggestions")
async def suggestions(request: SuggestRequest):
    """Four short questions tailored to the selected documents (cached).

    By default they are built instantly from the documents' key terms, so the
    AI model stays free for your real questions. Set LLM_SUGGESTIONS=true to
    let the model write them instead (it then runs at low priority).
    """
    key = tuple(sorted(set(request.document_ids)))
    if key in _suggestion_cache:
        return {"suggestions": _suggestion_cache[key], "cached": True}
    db = SessionLocal()
    try:
        docs = []
        for doc_id in key[:4]:
            doc = db.get(Document, doc_id)
            if doc is not None and doc.extracted_text:
                docs.append((doc.filename, doc.extracted_text))
    finally:
        db.close()
    if not docs:
        return {"suggestions": FALLBACK_SUGGESTIONS, "cached": False}

    result = quick_suggestions(docs) or FALLBACK_SUGGESTIONS
    if s.llm_suggestions:
        excerpts = [f"## {name}\n{text[:1500]}" for name, text in docs]
        prompt = (
            "DOCUMENT EXCERPTS:\n" + "\n\n".join(excerpts)
            + "\n\nWrite exactly 4 short, specific questions (max 12 words each) a reader could ask "
            "about these documents. One question per line, no numbering, no extra text."
        )
        try:
            raw = await generate(prompt, system="You write helpful questions. Output only the questions.",
                                 temperature=0.4, max_tokens=140, model=request.model, priority="background")
            items = [line.strip().lstrip("-*•0123456789.) ").strip().strip('"') for line in raw.splitlines()]
            items = [i for i in items if 8 <= len(i) <= 120][:4]
            if len(items) >= 2:
                result = items
        except Exception as exc:  # noqa: BLE001
            log.info("AI suggestions unavailable, using instant ones: %s", exc)
    _suggestion_cache[key] = result
    return {"suggestions": result, "cached": False}


# ============================================================
# ONE-PORT MODE: serve the built React app (frontend/dist) if present
# ============================================================

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="ui")
else:
    @app.get("/")
    def root():
        return {"name": s.app_name, "version": s.app_version, "status": "running", "docs": "/docs",
                "hint": "Run the frontend with 'npm run dev' in /frontend, or 'npm run build' to serve it from here."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app.main:app", host=s.host, port=s.port)
