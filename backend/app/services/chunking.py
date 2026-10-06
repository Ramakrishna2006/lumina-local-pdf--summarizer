import re

from backend.app.core.config import settings


s = settings()


def clean_text(text: str) -> str:
    """
    Normalize extracted document text.
    """

    if not text:
        return ""

    # Normalize whitespace
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Remove excessive spaces
    text = re.sub(
        r"[ \t]+",
        " ",
        text
    )

    # Remove excessive blank lines
    text = re.sub(
        r"\n{3,}",
        "\n\n",
        text
    )

    return text.strip()


def chunks(
    text: str,
    chunk_size: int | None = None,
    overlap: int | None = None,
    max_chunks: int | None = None
) -> list[str]:

    text = clean_text(text)

    if not text:
        return []

    chunk_size = s.chunk_size if chunk_size is None else chunk_size
    overlap = s.chunk_overlap if overlap is None else overlap
    max_chunks = s.max_chunks if max_chunks is None else max_chunks

    if chunk_size <= 0:
        raise ValueError(
            "chunk_size must be greater than zero."
        )

    if overlap < 0:
        raise ValueError(
            "chunk_overlap cannot be negative."
        )

    if overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap must be smaller than chunk_size."
        )

    result = []

    start = 0
    text_length = len(text)

    while start < text_length:

        end = min(
            start + chunk_size,
            text_length
        )

        # Prefer breaking at a paragraph
        if end < text_length:

            paragraph_break = text.rfind(
                "\n\n",
                start,
                end
            )

            if paragraph_break > start + chunk_size // 2:
                end = paragraph_break

            else:

                sentence_break = max(
                    text.rfind(".", start, end),
                    text.rfind("?", start, end),
                    text.rfind("!", start, end),
                )

                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 1

        piece = text[start:end].strip()

        if piece:
            result.append(piece)

        if len(result) >= max_chunks:
            break

        if end >= text_length:
            break

        next_start = end - overlap

        if next_start <= start:
            next_start = end

        start = next_start

    return result
