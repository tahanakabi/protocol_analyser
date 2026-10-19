"""pymupdf4llm layout boxes (page headers, section headers, text, lists, tables) mapped to source blocks."""

from pathlib import Path

from app.pdf_handlers.common import RawElement, assemble_blocks, markdown_to_text, page_sizes
from app.schemas import SourceBlock

_KIND_BY_CLASS = {
    "page-header": "margin",
    "page-footer": "margin",
    "section-header": "heading",
    "title": "heading",
    "table": "table",
    "picture": "skip",
}


def parse(pdf_path: Path) -> list[SourceBlock]:
    import pymupdf4llm

    chunks = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True, use_ocr=False, show_progress=False)
    elements: list[RawElement] = []
    for chunk in chunks:
        page = int(chunk["metadata"]["page_number"])
        markdown = chunk.get("text", "")
        for box in chunk.get("page_boxes", []):
            kind = _KIND_BY_CLASS.get(box.get("class", ""), "text")
            start, end = box.get("pos", (0, 0))
            text = markdown_to_text(markdown[start:end], keep_table=kind == "table")
            elements.append(RawElement(page, tuple(float(v) for v in box["bbox"]), text, kind))
    return assemble_blocks(elements, page_sizes(pdf_path))
