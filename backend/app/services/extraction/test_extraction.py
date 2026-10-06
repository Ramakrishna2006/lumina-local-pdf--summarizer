import asyncio
import sys

from backend.app.services.extraction.pdf import extract_pdf
from backend.app.services.extraction.image import extract_image


async def main():

    if len(sys.argv) != 3:
        print(
            "Usage:"
        )
        print(
            "python -m backend.app.services.extraction.test_extraction pdf <file>"
        )
        print(
            "python -m backend.app.services.extraction.test_extraction image <file>"
        )
        return

    file_type = sys.argv[1].lower()
    file_path = sys.argv[2]

    if file_type == "pdf":
        result = await extract_pdf(file_path)

    elif file_type == "image":
        result = await extract_image(file_path)

    else:
        print("Use: pdf or image")
        return

    print()
    print("=" * 60)
    print("EXTRACTION TEST")
    print("=" * 60)

    print("File type:", result["file_type"])
    print("OCR used:", result["ocr_used"])
    print("Pages:", result["page_count"])
    print("Characters:", len(result["text"]))

    print()
    print("TEXT PREVIEW")
    print("-" * 60)

    print(result["text"][:2000])

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
