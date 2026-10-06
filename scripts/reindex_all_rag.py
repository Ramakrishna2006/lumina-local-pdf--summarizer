"""Re-chunk and re-embed every processed document.

Use this after changing CHUNK_SIZE / CHUNK_OVERLAP or RAG_EMBEDDING_MODEL in .env,
or after upgrading from an older version of the project.

    python scripts/reindex_all_rag.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.database import SessionLocal, init_db  # noqa: E402
from backend.app.models.document import Document  # noqa: E402
from backend.app.services import rag_service  # noqa: E402
from backend.app.services.indexer import index_document  # noqa: E402
from backend.app.services.llm import close_client  # noqa: E402


async def main() -> None:
    init_db()
    db = SessionLocal()
    ok = failed = skipped = 0
    try:
        documents = db.query(Document).all()
        print(f"Documents found: {len(documents)}\n")
        for doc in documents:
            if doc.status != "completed" or not doc.extracted_text:
                print(f"- skip  {doc.filename} (status: {doc.status})")
                skipped += 1
                continue
            try:
                chunks = index_document(db, doc.id, doc.extracted_text)
                rag_service.invalidate(doc.id)
                info = await rag_service.index_document_rag(doc.id, db)
                print(f"- ok    {doc.filename}: {chunks} chunks, {info['dimensions']} dims")
                ok += 1
            except Exception as exc:  # noqa: BLE001
                print(f"- FAIL  {doc.filename}: {exc}")
                failed += 1
    finally:
        db.close()
        await close_client()
    print(f"\nDone. ok={ok} failed={failed} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
