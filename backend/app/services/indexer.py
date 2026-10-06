from sqlalchemy.orm import Session

from backend.app.models.chunk import DocumentChunk
from backend.app.services.chunking import chunks


def index_document(
    db: Session,
    document_id: str,
    text: str
) -> int:
    """
    Split extracted document text into chunks
    and store them locally in SQLite.
    """

    # Remove existing chunks.
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document_id
    ).delete(
        synchronize_session=False
    )

    document_chunks = chunks(text)

    for index, chunk_text in enumerate(
        document_chunks
    ):

        chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=index,
            text=chunk_text
        )

        db.add(chunk)

    db.commit()

    return len(document_chunks)
