"""marker-pdf JSON blocks mapped to source blocks."""

from pathlib import Path

import fitz

from app.pdf_handlers.common import RawElement, assemble_blocks, html_to_text, page_sizes
from app.schemas import SourceBlock

_KIND_BY_TYPE = {
    "PageHeader": "margin",
    "PageFooter": "margin",
    "SectionHeader": "heading",
    "Table": "table",
    "TableOfContents": "skip",
    "Picture": "skip",
    "Figure": "skip",
    "Reference": "skip",
}

_SURYA_BATCH_SERVERS = ("fast_layout", "ocr_error")


def _leaves(block):
    if not block.children:
        yield block
        return
    for child in block.children:
        yield from _leaves(child)


def _page_number(block_id: str) -> int:
    # Ids look like "/page/38/Text/5"; marker counts pages from zero.
    return int(block_id.split("/")[2]) + 1


def _stop_batch_servers() -> None:
    """surya spawns its layout and OCR-error servers detached and never stops them (about 1.3 GB each)."""
    try:
        from surya.inference.backends.spawn import _delete_sentinel, _read_sentinel, _stop_process
    except ImportError:
        return
    for backend in _SURYA_BATCH_SERVERS:
        sentinel = _read_sentinel(backend)
        if not sentinel:
            continue
        if sentinel.get("cleanup_kind") == "process" and sentinel.get("pid"):
            _stop_process(int(sentinel["pid"]), backend)
        _delete_sentinel(backend)


def parse(pdf_path: Path) -> list[SourceBlock]:
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict, shutdown_models

    models = create_model_dict()
    try:
        converter = PdfConverter(
            artifact_dict=models,
            # OCR needs a separate llama.cpp server; protocols have a text layer.
            config={"output_format": "json", "extract_images": False, "disable_ocr": True},
            renderer="marker.renderers.json.JSONRenderer",
        )
        rendered = converter(str(pdf_path))
    finally:
        shutdown_models(models)
        _stop_batch_servers()

    sizes = page_sizes(pdf_path)
    elements: list[RawElement] = []
    doc = fitz.open(pdf_path)
    try:
        for page_block in rendered.children:
            page = _page_number(page_block.id)
            width, height = sizes.get(page, (612.0, 792.0))
            px0, py0, px1, py1 = page_block.bbox
            sx = width / (px1 - px0) if px1 > px0 else 1.0
            sy = height / (py1 - py0) if py1 > py0 else 1.0
            for leaf in _leaves(page_block):
                if leaf is page_block:
                    continue
                kind = _KIND_BY_TYPE.get(leaf.block_type, "text")
                x0, y0, x1, y1 = leaf.bbox
                bbox = ((x0 - px0) * sx, (y0 - py0) * sy, (x1 - px0) * sx, (y1 - py0) * sy)
                text = html_to_text(leaf.html or "")
                if kind == "table":
                    # Without OCR marker rebuilds tables heuristically and drops many cells.
                    clipped = doc[page - 1].get_text("text", clip=fitz.Rect(bbox)).strip()
                    if len(clipped) > len(text):
                        text = clipped
                elements.append(RawElement(page, bbox, text, kind))
    finally:
        doc.close()
    return assemble_blocks(elements, sizes)
