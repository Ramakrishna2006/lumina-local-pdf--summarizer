"""Image text extraction (OCR) with Tesseract."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from backend.app.core.config import settings

s = settings()


def configure_tesseract() -> None:
    if s.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd


def extract_image_sync(path: str) -> dict:
    configure_tesseract()
    image_path = Path(path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image file not found: {image_path}")

    try:
        with Image.open(image_path) as image:
            image = ImageOps.exif_transpose(image)  # respect phone-camera rotation
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            # Upscale small images – Tesseract is much more accurate on larger text.
            if max(image.size) < 1500:
                factor = 1500 / max(image.size)
                image = image.resize((int(image.width * factor), int(image.height * factor)))
            text = pytesseract.image_to_string(image, lang=s.ocr_language, config="--oem 3 --psm 3").strip()
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError("Tesseract OCR is not installed. Install it and set TESSERACT_CMD in .env.") from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("Unable to process image with OCR.") from exc

    return {
        "text": text,
        "ocr_used": True,
        "page_count": 1,
        "file_type": image_path.suffix.lower().lstrip("."),
    }


async def extract_image(path: str) -> dict:
    return await asyncio.to_thread(extract_image_sync, path)
