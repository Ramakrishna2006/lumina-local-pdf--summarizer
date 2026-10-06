"""Retrieval-Augmented Generation (RAG) over local documents.

How it works
------------
1. Each document is split into chunks (``indexer.py``) and stored in SQLite.
2. Every chunk is embedded with a local Ollama embedding model and the
   normalised vectors are saved to ``storage/rag/<id>.npy`` (+ ``.json``).
3. A question is embedded once, compared to all chunk vectors with a single
   matrix multiplication, blended with a keyword score (hybrid search) and the
   best chunks become the LLM context.

Speed features
--------------
* Loaded indexes are cached in RAM (LRU) – no disk reads per question.
* Chunk keyword sets are pre-computed once per index.
* Query embeddings are cached, so regenerating an answer is instant.
* ``np.argpartition`` picks the top-k without sorting every chunk.
* If the embedding model is missing, retrieval silently falls back to
  keyword (BM25-style) search instead of failing.
* Documents are usable immediately with keyword search. The semantic
  ("smart search") index is built in the background, ONE document at a time,
  and pauses while an answer is being written so answers stay fast.
* Background indexing stops as soon as its document is deleted.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import Counter, OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.chunk import DocumentChunk
from backend.app.models.document import Document
from backend.app.services.llm import get_client, get_openai_client, is_openai

log = logging.getLogger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were",
    "what", "which", "who", "how", "why", "when", "where", "can", "could", "does", "do", "about",
    "this", "that", "with", "from", "into", "as", "by", "it", "its", "be", "been", "being",
    "their", "there", "these", "those", "tell", "me", "please", "explain", "give", "document",
    "you", "your", "i", "my", "we", "our", "will", "would", "should", "also", "more", "some",
}


def _stem(word: str) -> str:
    """Very light stemming so "firewalls" matches "firewall" and "stands"
    matches "stand" (keyword search and sentence focusing)."""
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", (text or "").lower()) if w not in STOPWORDS]


# ============================================================
# INDEX STORAGE
# ============================================================

def rag_dir() -> Path:
    path = Path(settings().rag_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _paths(document_id: str) -> tuple[Path, Path]:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", document_id)
    return rag_dir() / f"{safe}.json", rag_dir() / f"{safe}.npy"


@dataclass
class LoadedIndex:
    document_id: str
    embedding_model: str
    matrix: np.ndarray | None          # (n_chunks, dims) normalised, or None for keyword-only
    chunks: list[dict[str, Any]]
    token_counts: list[Counter] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    doc_freq: Counter = field(default_factory=Counter)
    avg_len: float = 1.0


_index_cache: "OrderedDict[str, LoadedIndex]" = OrderedDict()
_query_cache: "OrderedDict[tuple[str, str], np.ndarray]" = OrderedDict()
_index_locks: dict[str, asyncio.Lock] = {}
# document_id -> time of the last failed embedding attempt. While embeddings are
# unavailable we use keyword search and only retry every few minutes, so a
# missing embedding model never slows down every single question.
_semantic_failed: dict[str, float] = {}
RETRY_SEMANTIC_AFTER = 300.0


def _cache_put(document_id: str, index: LoadedIndex) -> None:
    _index_cache[document_id] = index
    _index_cache.move_to_end(document_id)
    while len(_index_cache) > max(1, settings().rag_cache_size):
        _index_cache.popitem(last=False)


def invalidate(document_id: str) -> None:
    _index_cache.pop(document_id, None)
    _semantic_failed.pop(document_id, None)


def delete_index(document_id: str) -> None:
    """Remove a document's vectors from RAM and disk (privacy on delete)."""
    invalidate(document_id)
    for path in _paths(document_id):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log.warning("Could not delete RAG file %s", path)


def _prepare_keywords(index: LoadedIndex) -> LoadedIndex:
    index.token_counts = [Counter(tokenize(c["text"])) for c in index.chunks]
    df: Counter = Counter()
    for counts in index.token_counts:
        df.update(counts.keys())
    index.doc_freq = df
    lengths = [sum(c.values()) for c in index.token_counts] or [1]
    index.lengths = lengths
    index.avg_len = max(1.0, sum(lengths) / len(lengths))
    return index


# ============================================================
# EMBEDDINGS
# ============================================================

async def embed(inputs: str | list[str]) -> list[list[float]]:
    s = settings()
    if is_openai():
        if not s.embedding_model:
            raise RuntimeError("No embedding model configured (OPENAI_EMBEDDING_MODEL) – using keyword search.")
        response = await get_openai_client().post(
            "/embeddings", json={"model": s.embedding_model, "input": inputs}
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Embedding model '{s.embedding_model}' failed ({response.status_code}).")
        data = sorted(response.json().get("data") or [], key=lambda d: d.get("index", 0))
        embeddings = [d["embedding"] for d in data if d.get("embedding")]
        if not embeddings:
            raise RuntimeError("The server returned no embeddings.")
        return embeddings
    response = await get_client().post(
        "/api/embed",
        json={
            "model": s.rag_embedding_model,
            "input": inputs,
            "keep_alive": s.llm_keep_alive,
            "truncate": True,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"Embedding model '{s.rag_embedding_model}' failed ({response.status_code}). "
            f"Run: ollama pull {s.rag_embedding_model}"
        )
    embeddings = response.json().get("embeddings") or []
    if not embeddings:
        raise RuntimeError(f"Ollama returned no embeddings for model '{s.rag_embedding_model}'.")
    return embeddings


async def _embed_query(question: str) -> np.ndarray:
    key = (settings().embedding_model, question.strip().lower())
    cached = _query_cache.get(key)
    if cached is not None:
        _query_cache.move_to_end(key)
        return cached
    vector = np.asarray((await embed(question))[0], dtype=np.float32)
    vector /= max(float(np.linalg.norm(vector)), 1e-12)
    _query_cache[key] = vector
    while len(_query_cache) > 256:
        _query_cache.popitem(last=False)
    return vector


# ============================================================
# INDEXING
# ============================================================

def _load_chunks(db: Session, document_id: str) -> list[dict[str, Any]]:
    rows = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .all()
    )
    return [{"chunk_index": int(r.chunk_index), "text": r.text} for r in rows if (r.text or "").strip()]


async def index_document_rag(document_id: str, db: Session, background: bool = False) -> dict[str, Any]:
    """Embed every chunk of a document and save the vector index to disk.

    With ``background=True`` the work pauses while answers are being written
    and stops early if the document is deleted.
    """
    s = settings()
    records = _load_chunks(db, document_id)
    if not records:
        raise RuntimeError("No text chunks are available for RAG indexing.")

    texts = [r["text"] for r in records]
    vectors: list[list[float]] = []
    batch = max(1, s.rag_embed_batch)
    started = time.perf_counter()
    for start in range(0, len(texts), batch):
        if background:
            await _wait_while_answering()
            if document_id in _cancelled:
                raise IndexCancelled(document_id)
        vectors.extend(await embed(texts[start:start + batch]))

    if background and document_id in _cancelled:
        raise IndexCancelled(document_id)
    if len(vectors) != len(texts):
        raise RuntimeError(f"Embedding count mismatch: expected {len(texts)}, got {len(vectors)}.")

    matrix = np.asarray(vectors, dtype=np.float32)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)

    meta_path, vec_path = _paths(document_id)
    np.save(vec_path, matrix)
    meta_path.write_text(
        json.dumps({
            "version": 3,
            "document_id": document_id,
            "embedding_model": s.embedding_model,
            "dimensions": int(matrix.shape[1]),
            "chunks": records,
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    _semantic_failed.pop(document_id, None)
    _cache_put(document_id, _prepare_keywords(LoadedIndex(document_id, s.embedding_model, matrix, records)))
    log.info("RAG index: doc=%s chunks=%d dims=%d %.1fs", document_id, len(records), matrix.shape[1], time.perf_counter() - started)
    return {
        "document_id": document_id,
        "chunks": len(records),
        "dimensions": int(matrix.shape[1]),
        "embedding_model": s.embedding_model,
    }


def rag_index_info(document_id: str) -> dict[str, Any] | None:
    meta_path, vec_path = _paths(document_id)
    if not meta_path.exists() or not vec_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("chunks", None)
        return meta
    except Exception:  # noqa: BLE001
        return None


def _load_from_disk(document_id: str) -> LoadedIndex | None:
    meta_path, vec_path = _paths(document_id)
    if not meta_path.exists() or not vec_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        matrix = np.load(vec_path).astype(np.float32, copy=False)
        if matrix.ndim != 2 or matrix.shape[0] != len(meta["chunks"]):
            return None
        return _prepare_keywords(LoadedIndex(document_id, meta.get("embedding_model", ""), matrix, meta["chunks"]))
    except Exception:  # noqa: BLE001
        log.exception("Could not read RAG index for %s", document_id)
        return None


async def get_index(document_id: str, db: Session) -> LoadedIndex:
    """Return the best index available *right now* – never blocks on embedding.

    * semantic index in RAM or on disk  -> hybrid search
    * otherwise                          -> keyword index now, and the semantic
                                            index is (re)built in the background
    """
    s = settings()
    cached = _index_cache.get(document_id)
    if cached is not None and (cached.matrix is not None or not s.rag_enabled):
        _index_cache.move_to_end(document_id)
        return cached

    lock = _index_locks.setdefault(document_id, asyncio.Lock())
    async with lock:
        cached = _index_cache.get(document_id)
        if cached is not None and cached.matrix is not None:
            return cached

        if s.rag_enabled:
            if rag_index_exists(document_id):
                index = await asyncio.to_thread(_load_from_disk, document_id)
                if index is not None and index.embedding_model == s.embedding_model:
                    _cache_put(document_id, index)
                    return index
            recently_failed = time.monotonic() - _semantic_failed.get(document_id, -1e9) < RETRY_SEMANTIC_AFTER
            if not recently_failed:
                schedule_background_index(document_id)

        if cached is not None:
            return cached
        index = _prepare_keywords(LoadedIndex(document_id, "", None, _load_chunks(db, document_id)))
        if not index.chunks:
            raise ValueError("This document has no searchable text.")
        _cache_put(document_id, index)
        return index


# ============================================================
# BACKGROUND "SMART SEARCH" INDEXING
# ============================================================

class IndexCancelled(Exception):
    """The document was deleted while its index was being built."""


_embed_lock: asyncio.Lock | None = None      # one document at a time
_pending: set[str] = set()                   # queued or being embedded
_cancelled: set[str] = set()                 # deleted documents
_tasks: set[asyncio.Task] = set()            # keep references to running tasks
_answers_running = 0                         # answers being written right now


def begin_answer() -> None:
    """An answer or summary started – background embedding pauses."""
    global _answers_running
    _answers_running += 1


def end_answer() -> None:
    global _answers_running
    _answers_running = max(0, _answers_running - 1)


@contextmanager
def answer_priority():
    """``with answer_priority():`` around answer/summary generation."""
    begin_answer()
    try:
        yield
    finally:
        end_answer()


async def _wait_while_answering() -> None:
    while _answers_running > 0:
        await asyncio.sleep(0.3)


def is_building(document_id: str) -> bool:
    return document_id in _pending


def is_cancelled(document_id: str) -> bool:
    return document_id in _cancelled


def cancel(document_id: str) -> None:
    """Stop background work for a deleted document and forget its index."""
    _cancelled.add(document_id)
    delete_index(document_id)


def schedule_background_index(document_id: str) -> None:
    """Queue the semantic index for a document (no-op if already queued)."""
    s = settings()
    if not s.rag_enabled or document_id in _pending or document_id in _cancelled:
        return
    _pending.add(document_id)
    task = asyncio.create_task(_build_in_background(document_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _build_in_background(document_id: str) -> None:
    global _embed_lock
    from backend.app.db.database import SessionLocal  # local import avoids a cycle

    if _embed_lock is None:
        _embed_lock = asyncio.Lock()
    try:
        async with _embed_lock:
            if document_id in _cancelled:
                return
            db = SessionLocal()
            try:
                await index_document_rag(document_id, db, background=True)
            finally:
                db.close()
    except IndexCancelled:
        log.info("Stopped indexing %s – the document was deleted.", document_id)
    except Exception as exc:  # noqa: BLE001
        _semantic_failed[document_id] = time.monotonic()
        log.warning("Smart search index failed for %s (keyword search is used): %s", document_id, exc)
    finally:
        _pending.discard(document_id)
        if document_id in _cancelled:
            delete_index(document_id)


def _bm25(index: LoadedIndex, q_tokens: list[str]) -> np.ndarray:
    n = len(index.chunks)
    scores = np.zeros(n, dtype=np.float32)
    if not q_tokens or n == 0:
        return scores
    k1, b = 1.4, 0.75
    for term in set(q_tokens):
        df = index.doc_freq.get(term, 0)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, counts in enumerate(index.token_counts):
            tf = counts.get(term, 0)
            if tf:
                length = index.lengths[i] or 1
                scores[i] += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * length / index.avg_len))
    if scores.max() > 0:
        scores /= scores.max()
    return scores


def _validate_documents(db: Session, document_ids: list[str]) -> dict[str, Document]:
    clean = list(dict.fromkeys(str(d).strip() for d in document_ids if str(d).strip()))
    if not clean:
        raise ValueError("At least one document must be selected.")
    documents: dict[str, Document] = {}
    for document_id in clean:
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document not found: {document_id}")
        if document.status != "completed":
            raise ValueError(f"Document '{document.filename}' is not ready yet (status: {document.status}).")
        documents[document_id] = document
    return documents


async def retrieve_multi_rag_context(
    db: Session,
    document_ids: list[str],
    question: str,
    top_k: int | None = None,
    max_chars: int | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Retrieve the best chunks across one or more documents.

    Returns (context_text, sources).
    """
    s = settings()
    question = (question or "").strip()
    if not question:
        raise ValueError("Question cannot be empty.")

    documents = _validate_documents(db, document_ids)

    # Speed: embed the question *while* the document indexes are loading.
    q_task: asyncio.Task | None = None
    has_semantic = any(
        (document_id in _index_cache and _index_cache[document_id].matrix is not None) or rag_index_exists(document_id)
        for document_id in documents
    )
    if s.rag_enabled and s.embedding_model and has_semantic:
        q_task = asyncio.create_task(_embed_query(question))
        q_task.add_done_callback(lambda task: task.cancelled() or task.exception())
    try:
        indexes = [await get_index(doc_id, db) for doc_id in documents]
    except BaseException:
        if q_task:
            q_task.cancel()
        raise

    q_tokens = tokenize(question)
    q_vector: np.ndarray | None = None
    if q_task is not None:
        if any(ix.matrix is not None for ix in indexes):
            try:
                q_vector = await q_task
            except Exception as exc:  # noqa: BLE001
                log.warning("Query embedding failed, using keyword search: %s", exc)
        else:
            q_task.cancel()

    candidates: list[tuple[float, str, dict[str, Any], str]] = []
    for index in indexes:
        if not index.chunks:
            continue
        lexical = _bm25(index, q_tokens)
        if q_vector is not None and index.matrix is not None and index.matrix.shape[1] == q_vector.shape[0]:
            semantic = index.matrix @ q_vector
            scores = 0.8 * semantic + 0.2 * lexical
            method = "hybrid"
        else:
            scores = lexical
            method = "keyword"

        k_local = min(len(scores), max(1, (top_k or s.rag_top_k)))
        best = np.argpartition(-scores, k_local - 1)[:k_local]
        for i in best:
            candidates.append((float(scores[i]), index.document_id, index.chunks[int(i)], method))

    if not candidates:
        raise ValueError("No searchable text was found in the selected documents.")

    candidates.sort(key=lambda c: c[0], reverse=True)
    k = max(1, min(int(top_k or s.rag_top_k), 12))
    budget = int(max_chars or s.rag_max_context_chars)

    # Ensure every selected document contributes at least its best chunk.
    selected: list[tuple[float, str, dict[str, Any], str]] = []
    seen_docs: set[str] = set()
    for cand in candidates:
        if cand[1] not in seen_docs:
            selected.append(cand)
            seen_docs.add(cand[1])
    for cand in candidates:
        if len(selected) >= max(k, len(seen_docs)):
            break
        if not any(cand is s for s in selected):
            selected.append(cand)
    # Fit the context budget. When the passages are longer than the budget we
    # keep the SENTENCES that matter for the question (not just the first part
    # of each passage): same information, less to read -> faster first word.
    kept: list[tuple[float, str, dict[str, Any], str, str]] = []
    total = sum(len(c[2]["text"]) + 80 for c in selected)
    share = max(350, budget // max(1, len(selected)) - 80)
    used = 0
    for score, doc_id, chunk, method in selected:
        room = budget - used - 80
        if room <= 200:
            break
        text = chunk["text"] if total <= budget else focus_text(chunk["text"], q_tokens, min(room, share))
        text = text[:room]
        kept.append((score, doc_id, chunk, method, text))
        used += len(text) + 80
    kept.sort(key=lambda c: c[0], reverse=True)

    parts: list[str] = []
    sources: list[dict[str, Any]] = []
    for rank, (score, doc_id, chunk, method, text) in enumerate(kept, start=1):
        filename = documents[doc_id].filename
        parts.append(f"[Source {rank} | {filename} | part {chunk['chunk_index'] + 1}]\n{text}")
        sources.append({
            "rank": rank,
            "document_id": doc_id,
            "filename": filename,
            "chunk_index": chunk["chunk_index"],
            "score": round(score, 4),
            "retrieval": method,
            "preview": re.sub(r"\s+", " ", chunk["text"][:220]).strip(),
        })

    return "\n\n---\n\n".join(parts), sources


# ============================================================
# WHOLE-DOCUMENT QUESTIONS ("summarize this", "key points", ...)
# ============================================================

_OVERVIEW_RE = re.compile(
    r"\b(summar\w*|overview|key points|main (?:ideas|points|topics)|tl;?dr|gist|outline|"
    r"what (?:is|are) (?:this|these|the) (?:document|documents|ppt|pdf|file|files|slides|presentation|notes) about)\b",
    re.IGNORECASE,
)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def focus_text(text: str, q_tokens: list[str], limit: int) -> str:
    """Shorten a passage to ``limit`` characters by keeping the sentences that
    share the most words with the question (in their original order).

    The first sentence (often a heading) gets a small bonus, and the sentence
    right after a matching one is kept when there is room, so explanations
    are not cut in half. Gaps are marked with "…".
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    sentences = [x.strip() for x in _SENTENCE_SPLIT.split(text) if x and x.strip()]
    if len(sentences) <= 1:
        return text[:limit]
    wanted = set(q_tokens)
    scores = []
    for i, sentence in enumerate(sentences):
        words = tokenize(sentence)
        hits = sum(1 for w in words if w in wanted)
        scores.append(hits / (1.0 + 0.015 * len(words)) + (0.35 if i == 0 else 0.0))
    # A sentence that follows a strong match usually continues the explanation.
    boosted = [sc + (0.5 * scores[i - 1] if i > 0 else 0.0) for i, sc in enumerate(scores)]
    keep: set[int] = set()
    seen: set[str] = set()
    used = 0
    for i in sorted(range(len(sentences)), key=lambda j: -boosted[j]):
        key = re.sub(r"\W+", " ", sentences[i].lower()).strip()
        if key in seen:                       # repeated headings / sentences add nothing
            continue
        cost = len(sentences[i]) + 3          # + space and a possible "…"
        if used + cost > limit:
            continue
        keep.add(i)
        seen.add(key)
        used += cost
    if not keep:
        return text[:limit]
    out: list[str] = []
    previous = -2
    for i in sorted(keep):
        if out and i != previous + 1:
            out.append("…")
        out.append(sentences[i])
        previous = i
    return " ".join(out)[:limit]


def wants_overview(question: str) -> bool:
    """Questions about the WHOLE document need excerpts from start to end,
    not just the few passages that best match the words of the question."""
    return bool(_OVERVIEW_RE.search(question or ""))


def overview_context(db: Session, document_ids: list[str], max_chars: int | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Evenly spaced chunks from every selected document (beginning to end)."""
    documents = _validate_documents(db, document_ids)
    budget = int(max_chars or settings().rag_max_context_chars)
    per_doc = max(800, budget // max(1, len(documents)))
    parts: list[str] = []
    sources: list[dict[str, Any]] = []
    rank = 0
    for doc_id, document in documents.items():
        records = _load_chunks(db, doc_id)
        if not records:
            continue
        take = max(1, min(len(records), per_doc // 700))
        step = (len(records) - 1) / max(take - 1, 1)
        picked = sorted({round(i * step) for i in range(take)})
        room = per_doc // len(picked)
        for i in picked:
            chunk = records[i]
            rank += 1
            text = chunk["text"][:room].strip()
            parts.append(f"[Source {rank} | {document.filename} | part {chunk['chunk_index'] + 1}]\n{text}")
            sources.append({
                "rank": rank,
                "document_id": doc_id,
                "filename": document.filename,
                "chunk_index": chunk["chunk_index"],
                "score": 1.0,
                "retrieval": "overview",
                "preview": re.sub(r"\s+", " ", chunk["text"][:220]).strip(),
            })
    if not parts:
        raise ValueError("No searchable text was found in the selected documents.")
    return "\n\n---\n\n".join(parts), sources


async def retrieve_rag_context(db: Session, document_id: str, question: str, top_k: int | None = None):
    return await retrieve_multi_rag_context(db, [document_id], question, top_k)


# Backwards-compatible helpers used by older scripts --------------------------

async def ensure_rag_index(document_id: str, db: Session) -> dict[str, Any]:
    await get_index(document_id, db)
    return rag_index_info(document_id) or {"document_id": document_id, "retrieval": "keyword"}


def rag_index_exists(document_id: str) -> bool:
    """Cheap check (no file reading) – used on every document list refresh."""
    meta_path, vec_path = _paths(document_id)
    return meta_path.exists() and vec_path.exists()
