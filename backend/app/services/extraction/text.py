from pathlib import Path
import json
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup


def read_text_file(path: str) -> str:
    """
    Read text using several common encodings.
    """

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp1252",
        "latin-1",
    ]

    for encoding in encodings:

        try:

            return Path(path).read_text(
                encoding=encoding
            )

        except UnicodeDecodeError:
            continue

    raise RuntimeError(
        "Unable to decode text file."
    )


def extract_text(
    path: str,
    extension: str
) -> dict:

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"Text file not found: {file_path}"
        )

    text = read_text_file(file_path).strip()

    return {
        "text": text,
        "ocr_used": False,
        "page_count": 1,
        "file_type": extension.lstrip("."),
    }


def extract_json(path: str) -> dict:

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"JSON file not found: {file_path}"
        )

    with open(
        file_path,
        "r",
        encoding="utf-8-sig"
    ) as file:

        data = json.load(file)

    text = json.dumps(
        data,
        indent=2,
        ensure_ascii=False
    )

    return {
        "text": text,
        "ocr_used": False,
        "page_count": 1,
        "file_type": "json",
    }


def extract_xml(path: str) -> dict:

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"XML file not found: {file_path}"
        )

    tree = ET.parse(file_path)

    root = tree.getroot()

    text_parts = []

    for element in root.iter():

        if element.text and element.text.strip():

            text_parts.append(
                element.text.strip()
            )

    text = "\n".join(text_parts)

    return {
        "text": text,
        "ocr_used": False,
        "page_count": 1,
        "file_type": "xml",
    }


def extract_html(path: str) -> dict:

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(
            f"HTML file not found: {file_path}"
        )

    html = read_text_file(file_path)

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # Remove elements that aren't useful document content
    for element in soup(
        ["script", "style", "noscript"]
    ):
        element.decompose()

    text = soup.get_text(
        separator="\n"
    )

    lines = []

    for line in text.splitlines():

        line = line.strip()

        if line:
            lines.append(line)

    final_text = "\n".join(lines)

    return {
        "text": final_text,
        "ocr_used": False,
        "page_count": 1,
        "file_type": "html",
    }
