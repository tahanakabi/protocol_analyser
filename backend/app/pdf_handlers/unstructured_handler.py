"""unstructured.io partition_pdf elements mapped to source blocks.

Only the "fast" (text layer) strategy is offered: "hi_res" needs Pillow>=11, which marker-pdf forbids.
"""

from pathlib import Path

from app.pdf_handlers.common import RawElement, assemble_blocks, group_cell_runs, html_to_text, page_sizes
from app.schemas import SourceBlock

_KIND_BY_CATEGORY = {
    "Header": "margin",
    "Footer": "margin",
    "PageNumber": "margin",
    "Title": "heading",
    "Table": "table",
    "Image": "skip",
    "PageBreak": "skip",
}


def _bbox(element, sizes: dict[int, tuple[float, float]], page: int) -> tuple[float, float, float, float]:
    coords = element.metadata.coordinates
    if coords is None or not coords.points:
        return (0.0, 0.0, 0.0, 0.0)
    width, height = sizes.get(page, (612.0, 792.0))
    system = coords.system
    sx = width / float(system.width) if getattr(system, "width", None) else 1.0
    sy = height / float(system.height) if getattr(system, "height", None) else 1.0
    xs = [float(x) * sx for x, _ in coords.points]
    ys = [float(y) * sy for _, y in coords.points]
    return (min(xs), min(ys), max(xs), max(ys))


def parse(pdf_path: Path) -> list[SourceBlock]:
    from unstructured.partition.pdf import partition_pdf

    sizes = page_sizes(pdf_path)
    partitioned = partition_pdf(filename=str(pdf_path), strategy="fast", languages=["eng"])
    elements: list[RawElement] = []
    for element in partitioned:
        page = element.metadata.page_number or 1
        kind = _KIND_BY_CATEGORY.get(element.category, "text")
        text = element.text or ""
        if kind == "table" and getattr(element.metadata, "text_as_html", None):
            text = html_to_text(element.metadata.text_as_html)
        elements.append(RawElement(page, _bbox(element, sizes, page), text, kind))
    # The fast strategy has no table detection and emits every table cell as its own element.
    return assemble_blocks(group_cell_runs(elements, sizes), sizes)
