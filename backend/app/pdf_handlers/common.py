"""Turn layout elements from third-party PDF libraries into the same SourceBlocks the built-in parser makes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Literal

import fitz

from app.pdf_block_builder import (
    NUMBER_ONLY_RE,
    Line,
    _clean_line,
    _detect_running_lines,
    _footer_cut,
    _header_cut,
    _is_structural_heading,
    _is_toc_line,
    _normalize_running,
    _update_section_stack,
)
from app.schemas import SourceBlock

ElementKind = Literal["heading", "text", "table", "margin", "skip"]

# Library headings this long are paragraphs the layout model mislabelled.
HEADING_MAX_CHARS = 160
SAME_ROW_TOLERANCE = 3.0
MARGIN_NOISE_MAX_CHARS = 60

_SENTENCE_END_RE = re.compile(r"[.:;!?)]$")


@dataclass
class RawElement:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    kind: ElementKind


def page_sizes(pdf_path) -> dict[int, tuple[float, float]]:
    doc = fitz.open(pdf_path)
    try:
        return {i + 1: (float(page.rect.width), float(page.rect.height)) for i, page in enumerate(doc)}
    finally:
        doc.close()


_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_MD_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_MD_STRONG_RE = re.compile(r"\*\*|__|~~")
_MD_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])")
_MD_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


def markdown_to_text(markdown: str, *, keep_table: bool = False) -> str:
    """Plain text that an LLM quote can match. Tables keep their pipes so rows stay readable."""
    text = _MD_BR_RE.sub("\n", markdown)
    text = _MD_STRONG_RE.sub("", text)
    text = _MD_ITALIC_RE.sub(r"\1", text)
    lines = []
    for raw in text.splitlines():
        line = raw if keep_table else _MD_BULLET_RE.sub("", _MD_HEADING_RE.sub("", raw))
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


class _HtmlText(HTMLParser):
    _BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "br", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.parts.append("\n" + " | ".join(self._row) + "\n")
            self._row = None
        elif tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        elif self._row is None:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    parser.close()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def _union(a, b) -> tuple[float, float, float, float]:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _join_number_rows(elements: list[RawElement]) -> list[RawElement]:
    """Attach a lone section or criterion number to the text that sits beside it on the same row."""
    joined: list[RawElement] = []
    index = 0
    while index < len(elements):
        current = elements[index]
        nxt = elements[index + 1] if index + 1 < len(elements) else None
        if (
            nxt is not None
            and nxt.page == current.page
            and current.kind in ("text", "heading")
            and nxt.kind in ("text", "heading")
            and NUMBER_ONLY_RE.match(current.text.strip())
            and abs(current.bbox[1] - nxt.bbox[1]) <= SAME_ROW_TOLERANCE
            and nxt.bbox[0] >= current.bbox[2]
        ):
            text = f"{current.text.strip()} {nxt.text.strip()}"
            joined.append(RawElement(current.page, _union(current.bbox, nxt.bbox), text, nxt.kind))
            index += 2
            continue
        joined.append(current)
        index += 1
    return joined


CELL_MAX_CHARS = 80
CELL_RUN_MIN = 4
CELL_RUN_MAX_GAP = 30.0


def _is_cell(element: RawElement, sizes: dict[int, tuple[float, float]]) -> bool:
    text = element.text.strip()
    height = sizes.get(element.page, (612.0, 792.0))[1]
    # Libraries often label short cells ("Medical history", "X") as titles; only numbered headings are sections.
    return (
        element.kind in ("text", "heading")
        and element.bbox[1] >= _header_cut(height)
        and element.bbox[3] <= _footer_cut(height)
        and "\n" not in text
        and len(text) <= CELL_MAX_CHARS
        and not _is_structural_heading(_clean_line(text))
    )


def _rows(cells: list[RawElement]) -> list[list[RawElement]]:
    rows: list[list[RawElement]] = []
    for cell in sorted(cells, key=lambda c: (c.bbox[1] + c.bbox[3]) / 2):
        center = (cell.bbox[1] + cell.bbox[3]) / 2
        if rows and abs(center - (rows[-1][0].bbox[1] + rows[-1][0].bbox[3]) / 2) <= SAME_ROW_TOLERANCE:
            rows[-1].append(cell)
        else:
            rows.append([cell])
    return [sorted(row, key=lambda c: c.bbox[0]) for row in rows]


def _flush_cells(run: list[RawElement], out: list[RawElement]) -> None:
    rows = _rows(run)
    if len(run) < CELL_RUN_MIN or not any(len(row) > 1 for row in rows):
        out.extend(run)
        return
    bbox = run[0].bbox
    for cell in run[1:]:
        bbox = _union(bbox, cell.bbox)
    text = "\n".join(" | ".join(c.text.strip() for c in row) for row in rows)
    out.append(RawElement(run[0].page, bbox, text, "table"))


def group_cell_runs(elements: list[RawElement], sizes: dict[int, tuple[float, float]]) -> list[RawElement]:
    """Join table cells that a text-layer library emitted one by one into a single table element.

    A run of short single-line elements counts as a table only if some row holds two or more of them,
    so ordinary single-column lists are left alone.
    """
    out: list[RawElement] = []
    run: list[RawElement] = []
    for element in _join_number_rows(elements):
        if run and (
            element.page != run[-1].page
            or not _is_cell(element, sizes)
            or element.bbox[1] - max(c.bbox[3] for c in run) > CELL_RUN_MAX_GAP
        ):
            _flush_cells(run, out)
            run = []
        if _is_cell(element, sizes):
            run.append(element)
        else:
            out.append(element)
    if run:
        _flush_cells(run, out)
    return out


def _is_toc_element(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    return sum(1 for line in lines if _is_toc_line(line)) * 2 >= len(lines)


def _heading_candidate(element: RawElement) -> bool:
    if element.kind == "heading":
        return len(element.text) <= HEADING_MAX_CHARS
    return element.kind == "text" and "\n" not in element.text and len(element.text) <= HEADING_MAX_CHARS


def _continues(previous: SourceBlock, element: RawElement, text: str) -> bool:
    """A wrapped sentence that the library split at a line break: no closing punctuation, lowercase next line."""
    if element.kind != "text" or previous.page != element.page:
        return False
    if _SENTENCE_END_RE.search(previous.text) or not text[:1].islower():
        return False
    line_height = max(element.bbox[3] - element.bbox[1], 1.0) / (text.count("\n") + 1)
    gap = element.bbox[1] - previous.bbox[3]
    return -1.0 <= gap <= line_height * 1.2 and abs(element.bbox[0] - previous.bbox[0]) <= 40


def assemble_blocks(elements: list[RawElement], sizes: dict[int, tuple[float, float]]) -> list[SourceBlock]:
    """Elements must already be in the library's reading order within each page."""
    by_page: dict[int, list[RawElement]] = {}
    for element in elements:
        if element.text.strip() and element.kind != "skip":
            by_page.setdefault(element.page, []).append(element)

    as_lines = {
        page: [Line(page=page, text=el.text, bbox=el.bbox, size=0.0, y0=el.bbox[1], y1=el.bbox[3]) for el in els]
        for page, els in by_page.items()
    }
    ref_height = next(iter(sizes.values()), (612.0, 792.0))[1]
    running = _detect_running_lines(as_lines, ref_height)

    blocks: list[SourceBlock] = []
    section_stack: list[str] = []

    for page in sorted(by_page):
        height = sizes.get(page, (612.0, ref_height))[1]
        top_cut, bottom_cut = _header_cut(height), _footer_cut(height)
        section_path = " > ".join(section_stack)
        block_index = 0
        page_start = len(blocks)

        for element in _join_number_rows(by_page[page]):
            text = element.text.strip()
            if element.kind == "margin" or _normalize_running(text) in running or _is_toc_element(text):
                continue

            if _heading_candidate(element) and _is_structural_heading(_clean_line(text)):
                section_stack = _update_section_stack(section_stack, _clean_line(text))
                section_path = " > ".join(section_stack)
                continue

            in_margin = element.bbox[1] < top_cut or element.bbox[3] > bottom_cut
            if in_margin and len(text) < MARGIN_NOISE_MAX_CHARS:
                continue

            previous = blocks[-1] if len(blocks) > page_start else None
            if previous is not None and previous.section_path == (section_path or None) and _continues(
                previous, element, text
            ):
                previous.text = f"{previous.text}\n{text}"
                previous.bbox = [float(v) for v in _union(previous.bbox, element.bbox)]
                continue

            blocks.append(
                SourceBlock(
                    id=f"p{page}_b{block_index}",
                    page=page,
                    bbox=[float(v) for v in element.bbox],
                    text=text,
                    section_path=section_path or None,
                )
            )
            block_index += 1

    return blocks
