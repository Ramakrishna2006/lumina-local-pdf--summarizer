"""Persistent chat sessions and messages."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.document import Document

log = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def chat_document_ids(chat: ChatSession) -> list[str]:
    ids = [str(i) for i in (chat.document_ids or []) if i]
    if chat.document_id and chat.document_id not in ids:
        ids.insert(0, chat.document_id)
    return ids


def create_chat(
    db: Session,
    document_id: str | None = None,
    title: str = "New Chat",
    document_ids: list[str] | None = None,
) -> ChatSession:
    ids = list(dict.fromkeys([d for d in ([document_id] if document_id else []) + (document_ids or []) if d]))
    if not ids:
        raise ValueError("Select at least one document.")
    for doc_id in ids:
        if db.get(Document, doc_id) is None:
            raise ValueError(f"Document not found: {doc_id}")

    now = utc_now()
    chat = ChatSession(
        id=str(uuid.uuid4()),
        document_id=ids[0],
        document_ids=ids,
        title=(title or "New Chat").strip()[:200] or "New Chat",
        created_at=now,
        updated_at=now,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


def get_chat(db: Session, chat_id: str) -> ChatSession | None:
    return db.get(ChatSession, chat_id)


def list_chats(db: Session, document_id: str | None = None) -> list[ChatSession]:
    chats = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    if document_id:
        chats = [c for c in chats if document_id in chat_document_ids(c)]
    return chats


def get_messages(db: Session, chat_id: str) -> list[ChatMessage]:
    return (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )


def recent_history(db: Session, chat_id: str, limit: int = 6) -> list[dict[str, str]]:
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.chat_id == chat_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def add_message(
    db: Session,
    chat_id: str,
    role: str,
    content: str,
    sources=None,
) -> ChatMessage:
    if role not in {"user", "assistant", "system"}:
        raise ValueError("Invalid message role.")
    content = (content or "").strip()
    if not content:
        raise ValueError("Message content cannot be empty.")

    chat = db.get(ChatSession, chat_id)
    if chat is None:
        raise ValueError("Chat not found.")

    now = utc_now()
    message = ChatMessage(chat_id=chat_id, role=role, content=content, sources=sources, created_at=now)
    db.add(message)
    chat.updated_at = now

    if role == "user" and chat.title in {"New Chat", ""}:
        title = " ".join(content.split())
        chat.title = (title[:57] + "...") if len(title) > 60 else title

    db.commit()
    db.refresh(message)
    return message


def rename_chat(db: Session, chat_id: str, title: str) -> ChatSession:
    chat = db.get(ChatSession, chat_id)
    if chat is None:
        raise ValueError("Chat not found.")
    chat.title = (title or "").strip()[:200] or chat.title
    db.commit()
    return chat


def delete_chat(db: Session, chat_id: str) -> None:
    db.query(ChatMessage).filter(ChatMessage.chat_id == chat_id).delete(synchronize_session=False)
    chat = db.get(ChatSession, chat_id)
    if chat is not None:
        db.delete(chat)
    db.commit()


def export_markdown(db: Session, chat: ChatSession) -> str:
    lines = [f"# {chat.title}", ""]
    names = []
    for doc_id in chat_document_ids(chat):
        doc = db.get(Document, doc_id)
        if doc:
            names.append(doc.filename)
    if names:
        lines += [f"_Documents: {', '.join(names)}_", ""]
    for m in get_messages(db, chat.id):
        who = "You" if m.role == "user" else "Lumina"
        lines += [f"### {who}", "", m.content, ""]
        if m.sources:
            refs = []
            for s in m.sources:
                if isinstance(s, dict):
                    refs.append(s.get("url") or f"{s.get('filename', 'Document')} (part {int(s.get('chunk_index', 0)) + 1})")
            if refs:
                lines += ["> Sources: " + "; ".join(refs), ""]
    return "\n".join(lines)
