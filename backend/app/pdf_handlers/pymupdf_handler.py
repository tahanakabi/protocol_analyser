"""Built-in parser: PyMuPDF text lines merged into paragraphs."""

from pathlib import Path

import fitz

from app.pdf_block_builder import build_blocks_from_document
from app.schemas import SourceBlock


def parse(pdf_path: Path) -> list[SourceBlock]:
    doc = fitz.open(pdf_path)
    try:
        return build_blocks_from_document(doc)
    finally:
        doc.close()
