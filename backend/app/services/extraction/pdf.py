"""PDF text extraction with automatic, parallel OCR for scanned pages.

Engines (the first one that is installed is used):

1. **PyMuPDF** (``pymupdf``) – fastest, best layout, used by default.
2. **pypdfium2** – Google's PDFium engine, a good fallback on new Python
   versions where PyMuPDF wheels may not exist yet.
3. **pypdf** – pure Python, always installable (text only, no OCR rendering).
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterator

import pytesseract
from PIL import Image

from backend.app.core.config import settings

log = logging.getLogger(__name__)
s = settings()

try:  # pragma: no cover - depends on what is installed
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    pymupdf = None

try:  # pragma: no cover
    import pypdfium2  # type: ignore
except ImportError:  # pragma: no cover
    pypdfium2 = None

try:  # pragma: no cover
    import pypdf  # type: ignore
except ImportError:  # pragma: no cover
    pypdf = None


def engine_name() -> str:
    if pymupdf is not None:
        return "pymupdf"
    if pypdfium2 is not None:
        return "pypdfium2"
    if pypdf is not None:
        return "pypdf"
    return "none"


def configure_tesseract() -> None:
    if s.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd


def _ocr_image(image: Image.Image) -> str:
    return pytesseract.image_to_string(image, lang=s.ocr_language, config="--oem 3 --psm 3").strip()


# ----------------------------------------------------------------------------
# Engine adapters: each yields (page_number, native_text) and offers a renderer
# ----------------------------------------------------------------------------

class _Pdf:
    page_count: int = 0

    def pages(self) -> Iterator[tuple[int, str]]:  # pragma: no cover - interface
        raise NotImplementedError

    def render(self, number: int) -> Image.Image | None:  # pragma: no cover - interface
        return None

    def close(self) -> None:
        pass


class _MuPdf(_Pdf):
    def __init__(self, path: Path) -> None:
        self.doc = pymupdf.open(path)
        if self.doc.needs_pass:
            self.doc.close()
            raise ValueError("Password-protected PDFs are not supported.")
        self.page_count = len(self.doc)

    def pages(self):
        for number, page in enumerate(self.doc, start=1):
            yield number, page.get_text("text").strip()

    def render(self, number):
        pix = self.doc[number - 1].get_pixmap(dpi=s.ocr_dpi, alpha=False)
        return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

    def close(self):
        self.doc.close()


class _Pdfium(_Pdf):
    def __init__(self, path: Path) -> None:
        try:
            self.doc = pypdfium2.PdfDocument(str(path))
        except pypdfium2.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise ValueError("Password-protected PDFs are not supported.") from exc
            raise
        self.page_count = len(self.doc)

    def pages(self):
        for i in range(self.page_count):
            page = self.doc[i]
            textpage = page.get_textpage()
            try:
                yield i + 1, (textpage.get_text_range() or "").strip()
            finally:
                textpage.close()
                page.close()

    def render(self, number):
        page = self.doc[number - 1]
        try:
            return page.render(scale=s.ocr_dpi / 72).to_pil().convert("RGB")
        finally:
            page.close()

    def close(self):
        self.doc.close()


class _PyPdf(_Pdf):
    def __init__(self, path: Path) -> None:
        self.reader = pypdf.PdfReader(str(path))
        if self.reader.is_encrypted:
            try:
                self.reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                raise ValueError("Password-protected PDFs are not supported.") from exc
        self.page_count = len(self.reader.pages)

    def pages(self):
        for i, page in enumerate(self.reader.pages, start=1):
            yield i, (page.extract_text() or "").strip()


def _open(path: Path) -> _Pdf:
    if pymupdf is not None:
        return _MuPdf(path)
    if pypdfium2 is not None:
        return _Pdfium(path)
    if pypdf is not None:
        return _PyPdf(path)
    raise RuntimeError("No PDF library installed. Run: pip install pymupdf")


# ----------------------------------------------------------------------------

def extract_pdf_sync(path: str, progress: Callable[[int, int], None] | None = None) -> dict:
    """Extract native text; OCR only pages that have little or no text.

    OCR runs in a thread pool (Tesseract is a separate process, so pages are
    recognised truly in parallel) which makes scanned PDFs several times faster.
    """
    configure_tesseract()
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    page_texts: dict[int, str] = {}
    ocr_pages: list[int] = []
    ocr_used = False

    pdf = _open(pdf_path)
    try:
        page_count = pdf.page_count
        for number, native in pdf.pages():
            if native:
                page_texts[number] = f"[Page {number}]\n{native}"
            if len(native) < s.ocr_min_chars:
                ocr_pages.append(number)

        can_render = type(pdf).render is not _Pdf.render
        if ocr_pages and can_render:
            workers = max(1, s.ocr_workers)
            batch_size = workers * 2  # only a few rendered pages in RAM at a time
            done = 0
            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for start in range(0, len(ocr_pages), batch_size):
                        batch = ocr_pages[start:start + batch_size]
                        images = [pdf.render(n) for n in batch]
                        for number, text in zip(batch, pool.map(_ocr_image, images), strict=True):
                            if text and len(text) > len(page_texts.get(number, "")):
                                ocr_used = True
                                page_texts[number] = f"[Page {number} - OCR]\n{text}"
                        done += len(batch)
                        if progress:
                            progress(done, len(ocr_pages))
            except pytesseract.TesseractNotFoundError:
                if not page_texts:
                    raise RuntimeError(
                        "This PDF needs OCR but Tesseract is not installed. "
                        "Install it and set TESSERACT_CMD in .env."
                    ) from None
                log.warning("Tesseract not found – scanned pages were skipped.")
    finally:
        pdf.close()

    text = "\n\n".join(page_texts[n] for n in sorted(page_texts)).strip()
    return {"text": text, "ocr_used": ocr_used, "page_count": page_count, "file_type": "pdf"}


async def extract_pdf(path: str) -> dict:
    return await asyncio.to_thread(extract_pdf_sync, path)
