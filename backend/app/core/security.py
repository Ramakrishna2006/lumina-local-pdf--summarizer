import re
import uuid
from pathlib import Path


def new_id() -> str:
    """Generate a unique document ID."""
    return str(uuid.uuid4())


def safe_filename(document_id: str, extension: str = ".pdf") -> str:
    """
    Create a safe server-side filename.

    The original user filename is never used for storage.
    """
    extension = extension.lower().strip()

    if not extension:
        extension = ".bin"

    if not extension.startswith("."):
        extension = "." + extension

    # Keep only a normal file extension.
    extension = re.sub(r"[^a-z0-9.]", "", extension)

    if not extension.startswith("."):
        extension = "." + extension

    return f"{document_id}{extension}"


def valid_pdf_signature(data: bytes) -> bool:
    """Check whether bytes begin with the PDF magic signature."""
    return data.startswith(b"%PDF-")


def safe_original_filename(filename: str) -> str:
    """
    Remove path traversal from an original filename.
    This is only for display/database metadata.
    """
    name = Path(filename or "").name

    # Remove control characters.
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)

    # Limit filename length.
    return name[:255]
