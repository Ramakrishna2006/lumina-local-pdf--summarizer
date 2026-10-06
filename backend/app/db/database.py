from __future__ import annotations

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import settings

s = settings()

_is_sqlite = s.database_url.startswith("sqlite")

engine = create_engine(
    s.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)


if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):
        """WAL lets the UI read while background jobs write -> no 'database is locked'."""
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _lightweight_migrations() -> None:
    """Add new columns to databases created by older versions of the app."""
    inspector = inspect(engine)
    if "chat_sessions" in inspector.get_table_names():
        columns = {c["name"] for c in inspector.get_columns("chat_sessions")}
        if "document_ids" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE chat_sessions ADD COLUMN document_ids JSON"))


def init_db() -> None:
    # Import models so SQLAlchemy registers every table before create_all().
    from backend.app.models import chat, chunk, document  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _lightweight_migrations()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
