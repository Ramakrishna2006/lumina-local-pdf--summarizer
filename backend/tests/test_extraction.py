"""Extraction tests. The PDF test builds a tiny PDF by hand, so it works with
whichever PDF engine is installed (PyMuPDF, pypdfium2 or pypdf)."""

from __future__ import annotations


def make_pdf(pages: list[str]) -> bytes:
    """Build a minimal, valid multi-page PDF with one line of text per page."""
    objects: list[bytes] = []
    n = len(pages)
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(n))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
    font_id = 3 + n * 2
    for i, text in enumerate(pages):
        content_id = 4 + i * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 11 Tf 40 740 Td ({safe}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_pdf_native_text_extraction(tmp_path, monkeypatch):
    from backend.app.services.extraction import pdf as pdf_module

    # Do not try OCR on these short test pages.
    monkeypatch.setattr(pdf_module.s, "ocr_min_chars", 0)
    path = tmp_path / "sample.pdf"
    path.write_bytes(make_pdf([f"Page {i + 1}: machine learning improves search quality." for i in range(3)]))

    result = pdf_module.extract_pdf_sync(str(path))
    assert pdf_module.engine_name() != "none"
    assert result["page_count"] == 3
    assert "machine learning" in result["text"]
    assert "[Page 3]" in result["text"]
    assert result["ocr_used"] is False


def test_text_json_and_code_extraction(tmp_path):
    import asyncio

    from backend.app.services.extraction.extractor import extract_document, supported_extensions
    from backend.app.services.extraction.text import extract_json, extract_text

    t = tmp_path / "notes.md"
    t.write_text("# Title\n\nSome **markdown** notes.", encoding="utf-8")
    assert "markdown" in extract_text(str(t), ".md")["text"]

    j = tmp_path / "data.json"
    j.write_text('{"name": "Lumina", "items": [1, 2, 3]}', encoding="utf-8")
    assert "Lumina" in extract_json(str(j))["text"]

    assert {".py", ".yaml", ".log"} <= supported_extensions()
    code = tmp_path / "script.py"
    code.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    assert "def add" in asyncio.run(extract_document(code)).text
