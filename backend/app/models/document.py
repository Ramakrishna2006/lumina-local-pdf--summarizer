from datetime import datetime, timezone

from sqlalchemy import String, Integer, Text, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class Document(Base):
    __tablename__ = "documents"

    # Identity
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True
    )

    # Original file information
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    stored_filename: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False
    )

    file_type: Mapped[str] = mapped_column(
        String(30),
        default="unknown"
    )

    mime_type: Mapped[str] = mapped_column(
        String(100),
        default="application/octet-stream"
    )

    size: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # Processing state
    status: Mapped[str] = mapped_column(
        String(30),
        default="queued"
    )

    stage: Mapped[str] = mapped_column(
        String(60),
        default="queued"
    )

    # Extraction information
    ocr_used: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    page_count: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    extracted_chars: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    # Complete normalized document text.
    #
    # This remains on the local SQLite database.
    # It is never sent to an external API.
    extracted_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # AI generated summary
    summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True
    )

    # Error information
    error: Mapped[str | None] = mapped_column(
        String(300),
        nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )
