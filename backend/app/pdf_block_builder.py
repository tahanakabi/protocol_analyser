"""Build logical source blocks from PDF pages (paragraphs + section context)."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

import fitz

from app.schemas import SourceBlock

# Running headers in these protocols sit near y=32–44. Section titles often start around y=66,
# so the header band must stay above that or the first heading on a page is discarded.
HEADER_BAND = 56.0
FOOTER_BAND_FRAC = 0.08
RUNNING_LINE_MIN_PAGES_RATIO = 0.32
RUNNING_LINE_MIN_COUNT = 3
PARAGRAPH_GAP_FACTOR = 1.75

SECTION_NUM_RE = re.compile(r"^(\d+(?:\.\d+)+)\s+(.+)$")
TOP_LEVEL_SECTION_RE = re.compile(r"^(\d+)\s+(.+)$")
NUMBER_ONLY_RE = re.compile(r"^\d+(?:\.\d+)*$")
TOC_LEADER_RE = re.compile(r"\.{4,}|…{2,}")
TOC_PAGE_RE = re.compile(r"(?:\.{2,}|\s)\d{1,4}\s*$")
WHITESPACE_RE = re.compile(r"\s+")
# Join a section number with its title when they sit on one baseline (common in protocol PDFs).
NUMBER_TITLE_MAX_GAP = 80.0
NUMBER_TITLE_MAX_X = 220.0
BASELINE_TOLERANCE = 2.0


@dataclass
class Line:
    page: int
    text: str
    bbox: tuple[float, float, float, float]
    size: float
    y0: float
    y1: float

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


def _normalize_running(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.strip()).lower()


def _union_bbox(a: tuple[float, float, float, float], b: tuple[float, float, float, float]):
    return (
        min(a[0], b[0]),
        min(a[1], b[1]),
        max(a[2], b[2]),
        max(a[3], b[3]),
    )


def _lines_from_page_dict(page: fitz.Page, page_number: int) -> list[Line]:
    data = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    lines: list[Line] = []
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            parts: list[str] = []
            sizes: list[float] = []
            for span in spans:
                t = span.get("text", "")
                if t:
                    parts.append(t)
                    sizes.append(float(span.get("size", 10)))
            text = "".join(parts).strip()
            if not text:
                continue
            bbox = tuple(line["bbox"])
            size = statistics.median(sizes) if sizes else 10.0
            lines.append(
                Line(
                    page=page_number,
                    text=text,
                    bbox=bbox,
                    size=size,
                    y0=bbox[1],
                    y1=bbox[3],
                )
            )
    lines.sort(key=lambda ln: (ln.y0, ln.bbox[0]))
    return lines


def _header_cut(page_height: float) -> float:
    return min(HEADER_BAND, page_height * 0.09)


def _footer_cut(page_height: float) -> float:
    return page_height * (1.0 - FOOTER_BAND_FRAC)


def _detect_running_lines(all_page_lines: dict[int, list[Line]], page_height: float) -> set[str]:
    counts: dict[str, int] = {}
    n_pages = len(all_page_lines)
    if n_pages == 0:
        return set()

    top_cut = _header_cut(page_height)
    bottom_cut = _footer_cut(page_height)

    for lines in all_page_lines.values():
        seen_on_page: set[str] = set()
        for ln in lines:
            in_header = ln.y0 < top_cut
            in_footer = ln.y1 > bottom_cut
            if not (in_header or in_footer):
                continue
            key = _normalize_running(ln.text)
            if len(key) < 4:
                continue
            if key in seen_on_page:
                continue
            seen_on_page.add(key)
            counts[key] = counts.get(key, 0) + 1

    threshold = max(RUNNING_LINE_MIN_COUNT, int(n_pages * RUNNING_LINE_MIN_PAGES_RATIO))
    return {text for text, c in counts.items() if c >= threshold}


def _clean_line(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text.strip())


def _heading_level(text: str) -> int | None:
    """Numbered protocol headings only. Cover titles and all-caps labels are not headings."""
    stripped = _clean_line(text)
    if _is_toc_line(stripped):
        return None
    m = SECTION_NUM_RE.match(stripped)
    if m:
        title = m.group(2).strip()
        if len(title) < 2 or title.endswith(","):
            return None
        return m.group(1).count(".") + 1
    m = TOP_LEVEL_SECTION_RE.match(stripped)
    if m and m.group(2).isupper() and len(m.group(2).split()) <= 12:
        return 1
    return None


def _is_toc_line(text: str) -> bool:
    stripped = _clean_line(text)
    if TOC_LEADER_RE.search(stripped):
        return True
    return bool(TOC_PAGE_RE.search(stripped) and re.match(r"^\d+(?:\.\d+)*\s+", stripped))


def _is_structural_heading(text: str) -> bool:
    return _heading_level(text) is not None


def _coalesce_numbered_rows(lines: list[Line]) -> list[Line]:
    """Join '5.1' + 'Inclusion Criteria' when the PDF places them on one baseline."""
    if not lines:
        return []
    ordered = sorted(lines, key=lambda ln: (ln.y0, ln.bbox[0]))
    merged: list[Line] = []
    index = 0
    while index < len(ordered):
        group = [index]
        baseline = ordered[index].y0
        nxt = index + 1
        while nxt < len(ordered) and abs(ordered[nxt].y0 - baseline) <= BASELINE_TOLERANCE:
            group.append(nxt)
            nxt += 1
        group.sort(key=lambda k: ordered[k].bbox[0])
        consumed: set[int] = set()
        for left_i, right_i in zip(group, group[1:]):
            if left_i in consumed or right_i in consumed:
                continue
            left, right = ordered[left_i], ordered[right_i]
            gap = right.bbox[0] - left.bbox[2]
            if (
                NUMBER_ONLY_RE.match(left.text.strip())
                and 2 <= gap <= NUMBER_TITLE_MAX_GAP
                and right.bbox[0] <= NUMBER_TITLE_MAX_X
            ):
                merged.append(
                    Line(
                        page=left.page,
                        text=f"{left.text.strip()} {right.text.strip()}",
                        bbox=_union_bbox(left.bbox, right.bbox),
                        size=max(left.size, right.size),
                        y0=min(left.y0, right.y0),
                        y1=max(left.y1, right.y1),
                    )
                )
                consumed.add(left_i)
                consumed.add(right_i)
        for key in group:
            if key not in consumed:
                merged.append(ordered[key])
        index = nxt
    merged.sort(key=lambda ln: (ln.y0, ln.bbox[0]))
    return merged


def _section_title_from_line(text: str) -> str:
    stripped = _clean_line(text)
    m = SECTION_NUM_RE.match(stripped)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}".strip()
    m = TOP_LEVEL_SECTION_RE.match(stripped)
    if m:
        return f"{m.group(1)} {m.group(2).strip()}".strip()
    return stripped


def _update_section_stack(stack: list[str], heading_text: str) -> list[str]:
    level = _heading_level(heading_text)
    title = _section_title_from_line(heading_text)
    if level is None:
        level = len(stack) + 1
    stack = stack[: max(0, level - 1)]
    stack.append(title)
    return stack


def _should_continue_paragraph(prev: Line, nxt: Line) -> bool:
    gap = nxt.y0 - prev.y1
    threshold = max(prev.height, nxt.height) * PARAGRAPH_GAP_FACTOR
    return gap <= threshold


def _flush_paragraph(
    lines: list[Line],
    section_path: str,
    page_number: int,
    block_index: int,
) -> SourceBlock | None:
    if not lines:
        return None
    text = "\n".join(ln.text for ln in lines)
    text = text.strip()
    if not text:
        return None
    bbox = lines[0].bbox
    for ln in lines[1:]:
        bbox = _union_bbox(bbox, ln.bbox)
    return SourceBlock(
        id=f"p{page_number}_b{block_index}",
        page=page_number,
        bbox=[float(x) for x in bbox],
        text=text,
        section_path=section_path or None,
    )


def coalesced_lines(doc: fitz.Document) -> list[tuple[int, str]]:
    """Reading-order lines with section numbers joined to their titles."""
    rows: list[tuple[int, str]] = []
    for page_index in range(len(doc)):
        page_number = page_index + 1
        for line in _coalesce_numbered_rows(_lines_from_page_dict(doc[page_index], page_number)):
            rows.append((page_number, _clean_line(line.text)))
    return rows


def build_blocks_from_document(doc: fitz.Document) -> list[SourceBlock]:
    all_page_lines: dict[int, list[Line]] = {}
    page_heights: dict[int, float] = {}

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_number = page_index + 1
        page_heights[page_number] = float(page.rect.height)
        all_page_lines[page_number] = _lines_from_page_dict(page, page_number)

    return build_blocks_from_lines(all_page_lines, page_heights)


def build_blocks_from_lines(
    all_page_lines: dict[int, list[Line]],
    page_heights: dict[int, float],
) -> list[SourceBlock]:
    """Paragraphs, numbered-heading section paths and running-header removal for any source of text lines."""
    ref_height = next(iter(page_heights.values()), 792.0)
    running = _detect_running_lines(all_page_lines, ref_height)

    blocks: list[SourceBlock] = []
    section_stack: list[str] = []

    for page_number in sorted(all_page_lines.keys()):
        lines = _coalesce_numbered_rows(all_page_lines[page_number])
        page_h = page_heights[page_number]
        top_cut = _header_cut(page_h)
        bottom_cut = _footer_cut(page_h)

        para_lines: list[Line] = []
        section_path = " > ".join(section_stack)
        block_index = 0

        def flush() -> None:
            nonlocal block_index, section_path
            block = _flush_paragraph(para_lines, section_path, page_number, block_index)
            if block:
                blocks.append(block)
                block_index += 1
            para_lines.clear()

        for ln in lines:
            if _normalize_running(ln.text) in running or _is_toc_line(ln.text):
                flush()
                continue

            if _is_structural_heading(ln.text):
                flush()
                section_stack = _update_section_stack(section_stack, ln.text)
                section_path = " > ".join(section_stack)
                continue

            if ln.y0 < top_cut or ln.y1 > bottom_cut:
                # Page numbers and other one-off margin noise. Headings already handled above.
                if len(ln.text.strip()) < 60:
                    continue

            if not para_lines:
                para_lines.append(ln)
                continue
            if _should_continue_paragraph(para_lines[-1], ln):
                para_lines.append(ln)
            else:
                flush()
                para_lines.append(ln)

        flush()

    return blocks
