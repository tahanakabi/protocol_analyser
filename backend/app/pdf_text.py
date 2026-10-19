from pathlib import Path

import fitz


def extract_text_with_page_markers(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    parts: list[str] = []
    for page_index in range(len(doc)):
        page = doc[page_index]
        text = page.get_text("text").strip()
        parts.append(f"[Page {page_index + 1}]\n{text}")
    doc.close()
    return "\n\n".join(parts)


def extract_page_text(pdf_path: Path, page_number: int) -> str:
    """page_number is 1-based."""
    doc = fitz.open(pdf_path)
    if page_number < 1 or page_number > len(doc):
        doc.close()
        return ""
    text = doc[page_number - 1].get_text("text").strip()
    doc.close()
    return text
