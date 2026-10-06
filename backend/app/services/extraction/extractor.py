from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from backend.app.services.extraction.pdf import extract_pdf
from backend.app.services.extraction.office import extract_docx, extract_pptx
from backend.app.services.extraction.spreadsheet import (
    extract_xlsx,
    extract_xls,
    extract_csv,
)
from backend.app.services.extraction.text import (
    extract_text,
    extract_json,
    extract_xml,
    extract_html,
)
from backend.app.services.extraction.image import extract_image


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".md",
    ".markdown",
    ".rst",
    ".log",
    ".tex",
    ".yaml",
    ".yml",
    ".ini",
    ".toml",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".sql",
    ".sh",
    ".css",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".png",
    ".jpg",
    ".jpeg",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
}


# Plain-text formats (notes, docs, logs, config files and source code).
TEXT_LIKE = {
    ".txt", ".md", ".markdown", ".rst", ".log", ".tex", ".yaml", ".yml", ".ini", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".h", ".cpp", ".cs", ".go", ".rs",
    ".php", ".rb", ".sql", ".sh", ".css",
}


@dataclass
class ExtractionResult:
    text: str
    page_count: int = 0
    ocr_used: bool = False


def supported_extensions() -> set[str]:
    """
    Return all supported document extensions.
    """
    return set(SUPPORTED_EXTENSIONS)


def is_supported(filename: str) -> bool:
    """
    Check whether a filename has a supported extension.
    """
    extension = Path(filename).suffix.lower()
    return extension in SUPPORTED_EXTENSIONS


def _normalize_result(result, extension: str) -> ExtractionResult:
    """
    Convert the existing extraction functions' return values
    into one consistent ExtractionResult object.

    The individual extractors in this project may return dictionaries
    or strings depending on the file type.
    """

    if isinstance(result, ExtractionResult):
        return result

    if isinstance(result, str):
        return ExtractionResult(
            text=result,
            page_count=1,
            ocr_used=False,
        )

    if not isinstance(result, dict):
        raise ValueError(
            f"Extractor returned an unsupported result for {extension}: "
            f"{type(result).__name__}"
        )

    text = result.get("text", "")

    if text is None:
        text = ""

    text = str(text)

    page_count = result.get(
        "page_count",
        result.get(
            "pages",
            result.get(
                "slide_count",
                result.get("sheet_count", 1),
            ),
        ),
    )

    try:
        page_count = int(page_count or 0)
    except (TypeError, ValueError):
        page_count = 0

    ocr_used = bool(
        result.get(
            "ocr_used",
            result.get(
                "ocr",
                False,
            ),
        )
    )

    return ExtractionResult(
        text=text,
        page_count=page_count,
        ocr_used=ocr_used,
    )


async def extract_document(
    path: str | Path,
    file_type: str | None = None,
) -> ExtractionResult:
    """
    Main document extraction entry point.

    This function is used by main.py.

    Supports:
        PDF
        DOCX
        PPTX
        XLSX
        XLS
        CSV
        TXT
        MD
        JSON
        XML
        HTML
        Images with OCR
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Document file not found: {path}"
        )

    extension = path.suffix.lower()

    # file_type may be supplied as ".pptx", "pptx",
    # or occasionally as a MIME type.
    if file_type:
        normalized_file_type = str(file_type).lower().strip()

        if normalized_file_type.startswith("."):
            extension = normalized_file_type
        elif "/" not in normalized_file_type:
            extension = "." + normalized_file_type

    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type: {extension or 'unknown'}"
        )

    # PDF
    if extension == ".pdf":
        result = await extract_pdf(str(path))
        return _normalize_result(result, extension)

    # Word
    if extension == ".docx":
        result = await asyncio.to_thread(extract_docx, str(path))
        return _normalize_result(result, extension)

    # PowerPoint
    if extension == ".pptx":
        result = await asyncio.to_thread(extract_pptx, str(path))
        return _normalize_result(result, extension)

    # Excel
    if extension == ".xlsx":
        result = await asyncio.to_thread(extract_xlsx, str(path))
        return _normalize_result(result, extension)

    if extension == ".xls":
        result = await asyncio.to_thread(extract_xls, str(path))
        return _normalize_result(result, extension)

    # CSV
    if extension == ".csv":
        result = await asyncio.to_thread(extract_csv, str(path))
        return _normalize_result(result, extension)

    # Plain text / Markdown
    if extension in TEXT_LIKE:
        result = await asyncio.to_thread(extract_text, str(path), extension)
        return _normalize_result(result, extension)

    # JSON
    if extension == ".json":
        result = await asyncio.to_thread(extract_json, str(path))
        return _normalize_result(result, extension)

    # XML
    if extension == ".xml":
        result = await asyncio.to_thread(extract_xml, str(path))
        return _normalize_result(result, extension)

    # HTML
    if extension in {".html", ".htm"}:
        result = await asyncio.to_thread(extract_html, str(path))
        return _normalize_result(result, extension)

    # Images → OCR
    if extension in {
        ".png",
        ".jpg",
        ".jpeg",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
    }:
        result = await extract_image(str(path))
        normalized = _normalize_result(result, extension)

        # Image extraction uses OCR.
        normalized.ocr_used = True

        return normalized

    raise ValueError(
        f"Unsupported file type: {extension or 'unknown'}"
    )


async def extract_file(
    path: str,
    filename: str,
) -> dict:
    """
    Backward-compatible wrapper for older code.

    Existing code that calls extract_file() can continue working.
    """

    result = await extract_document(path, filename)

    return {
        "text": result.text,
        "page_count": result.page_count,
        "ocr_used": result.ocr_used,
    }
