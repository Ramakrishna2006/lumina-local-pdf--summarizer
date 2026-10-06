# Re-export models so "import backend.app.models" registers every table.
from backend.app.models.document import Document
from backend.app.models.chunk import DocumentChunk
from backend.app.models.chat import ChatSession, ChatMessage
__all__ = ["Document", "DocumentChunk", "ChatSession", "ChatMessage"]
