"""In-memory answer cache.

Asking the same question about the same documents (with the same style,
language, model and conversation so far) returns the stored answer instantly
instead of running the LLM again. The cache lives only in RAM, is bounded
(LRU) and is cleared for a document whenever that document is deleted,
re-processed or re-indexed – so stale answers are never served.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from backend.app.core.config import settings


@dataclass
class CachedAnswer:
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    document_ids: tuple[str, ...] = ()


_lock = threading.Lock()
_cache: "OrderedDict[str, CachedAnswer]" = OrderedDict()
_hits = 0
_misses = 0

_SPACE_RE = re.compile(r"\s+")


def _normalize(question: str) -> str:
    q = _SPACE_RE.sub(" ", (question or "").strip().lower())
    return q.rstrip(" ?.!")


def make_key(
    *,
    question: str,
    document_ids: list[str],
    style: str,
    model: str,
    language: str,
    history: list[dict[str, str]] | None,
) -> str:
    payload = {
        "q": _normalize(question),
        "d": sorted(document_ids),
        "s": style,
        "m": model,
        "l": language,
        "h": [(h.get("role"), (h.get("content") or "")[:600]) for h in (history or [])],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def get(key: str) -> CachedAnswer | None:
    global _hits, _misses
    if not settings().answer_cache_enabled:
        return None
    with _lock:
        item = _cache.get(key)
        if item is None:
            _misses += 1
            return None
        _cache.move_to_end(key)
        _hits += 1
        return item


def put(key: str, answer: str, sources: list[dict[str, Any]], document_ids: list[str]) -> None:
    s = settings()
    if not s.answer_cache_enabled or not answer.strip():
        return
    with _lock:
        _cache[key] = CachedAnswer(answer, sources, tuple(document_ids))
        _cache.move_to_end(key)
        while len(_cache) > max(1, s.answer_cache_size):
            _cache.popitem(last=False)


def invalidate_document(document_id: str) -> int:
    """Drop every cached answer that used this document."""
    with _lock:
        stale = [k for k, v in _cache.items() if document_id in v.document_ids]
        for k in stale:
            _cache.pop(k, None)
        return len(stale)


def clear() -> None:
    global _hits, _misses
    with _lock:
        _cache.clear()
        _hits = _misses = 0


def stats() -> dict[str, int]:
    with _lock:
        return {"entries": len(_cache), "hits": _hits, "misses": _misses}
