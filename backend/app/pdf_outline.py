"""Build a nested outline from the protocol table of contents and attach paragraph blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.pdf_block_builder import TOC_LEADER_RE, coalesced_lines
from app.schemas import DocumentOutline, OutlineNode, SourceBlock, SourceIndex

NUMBERED_TOC_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\s+(?P<body>.+)$")
PAGE_AT_END_RE = re.compile(r"(\d{1,4})\s*$")
SECTION_START_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")
MIN_NUMBERED_TOC_ENTRIES = 3

# Longest phrase wins. The first phrase that matches any node is the one used.
EXTRACTION_NODE_PHRASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "study_objectives": (
        ("objectives and endpoints", "study objectives", "objectives"),
        ("synopsis",),
    ),
    "endpoints": (("objectives and endpoints", "study endpoints", "endpoints"),),
    "inclusion_criteria": (("inclusion criteria", "inclusion criterion", "criteria for inclusion"),),
    "exclusion_criteria": (("exclusion criteria", "exclusion criterion", "criteria for exclusion"),),
    "visits": (
        ("schedule of activities", "schedule of assessments", "study visits", "visit schedule"),
    ),
    "key_assessments_and_procedures": (
        ("study assessments and procedures", "assessments and procedures", "study assessments"),
    ),
    "safety_monitoring_rules": (
        ("adverse events", "serious adverse events", "data monitoring", "data safety monitoring", "stopping rule"),
    ),
}

# These fields should include every matching section, not only the longest phrase.
MATCH_ANY_SECTIONS = frozenset({"safety_monitoring_rules"})


@dataclass
class _TocEntry:
    number: str | None
    title: str
    page: int


@dataclass
class OutlineSelection:
    blocks: list[SourceBlock]
    labels: list[str]


def _clean_title(body: str) -> tuple[str, int] | None:
    match = PAGE_AT_END_RE.search(body)
    if match is None:
        return None
    title = body[: match.start()]
    title = TOC_LEADER_RE.sub(" ", title)
    title = re.sub(r"[\s.·…]+$", "", title).strip()
    title = re.sub(r"\s+", " ", title)
    if len(title) < 2:
        return None
    return title, int(match.group(1))


def _parse_toc_line(text: str) -> _TocEntry | None:
    if not TOC_LEADER_RE.search(text):
        return None
    numbered = NUMBERED_TOC_RE.match(text)
    if numbered:
        parsed = _clean_title(numbered.group("body"))
        if parsed is None:
            return None
        title, page = parsed
        if title.upper() == "TABLE OF CONTENTS":
            return None
        return _TocEntry(number=numbered.group("num"), title=title, page=page)

    parsed = _clean_title(text)
    if parsed is None:
        return None
    title, page = parsed
    if title.upper() in {"TABLE OF CONTENTS", "CONTENTS"}:
        return None
    if title != title.upper():
        return None
    return _TocEntry(number=None, title=title, page=page)


def _wrapped_heading_start(text: str) -> tuple[str, str] | None:
    """Numbered contents row whose title continues on the next line."""
    if TOC_LEADER_RE.search(text):
        return None
    match = NUMBERED_TOC_RE.match(text)
    if match is None:
        return None
    return match.group("num"), match.group("body").strip()


def _entries_on_page(lines: list[str]) -> list[_TocEntry]:
    entries: list[_TocEntry] = []
    pending: tuple[str, str] | None = None
    for text in lines:
        started = _wrapped_heading_start(text)
        if started is not None:
            pending = started
            continue
        entry = _parse_toc_line(text)
        if entry is not None and pending is not None and entry.number is None:
            title = f"{pending[1]} {entry.title}".strip()
            entries.append(_TocEntry(number=pending[0], title=title, page=entry.page))
            pending = None
            continue
        if pending is not None and entry is None:
            pending = (pending[0], f"{pending[1]} {text}".strip())
            continue
        pending = None
        if entry is not None:
            entries.append(entry)
    return entries


def _toc_pages(lines_by_page: dict[int, list[str]]) -> list[int]:
    numbered_counts = {
        page: sum(1 for entry in _entries_on_page(lines) if entry.number)
        for page, lines in lines_by_page.items()
    }
    marked = {
        page
        for page, lines in lines_by_page.items()
        if any("table of contents" in line.lower() for line in lines) or numbered_counts.get(page, 0) >= 4
    }
    if not marked:
        return []
    start = min(marked)
    pages = []
    page = start
    last = max(lines_by_page)
    while page <= last:
        count = numbered_counts.get(page, 0)
        if page not in marked and count < 2:
            break
        if count or page in marked:
            pages.append(page)
        page += 1
    return pages


def _level(number: str | None) -> int:
    if not number:
        return 1
    return number.count(".") + 1


def _build_tree(entries: list[_TocEntry]) -> list[OutlineNode]:
    roots: list[OutlineNode] = []
    stack: list[OutlineNode] = []
    seen_numbers: set[str] = set()
    for entry in entries:
        if entry.number and entry.number in seen_numbers:
            continue
        if entry.number:
            seen_numbers.add(entry.number)
        node = OutlineNode(
            number=entry.number,
            title=entry.title,
            page_start=entry.page,
            page_end=entry.page,
        )
        level = _level(entry.number)
        while stack and _level(stack[-1].number) >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def _walk(nodes: list[OutlineNode]) -> list[OutlineNode]:
    ordered: list[OutlineNode] = []

    def visit(node: OutlineNode) -> None:
        ordered.append(node)
        for child in node.children:
            visit(child)

    for node in nodes:
        visit(node)
    return ordered


def _body_headings(lines_by_page: dict[int, list[str]], toc_pages: set[int]) -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for page, lines in lines_by_page.items():
        if page in toc_pages:
            continue
        for text in lines:
            if TOC_LEADER_RE.search(text):
                continue
            match = SECTION_START_RE.match(text)
            if match is None:
                continue
            number, title = match.group(1), match.group(2).strip()
            if number.count(".") == 0 and title != title.upper():
                continue
            found.setdefault(number, []).append((page, title))
    return found


def _apply_body_pages(nodes: list[OutlineNode], headings: dict[str, list[tuple[int, str]]]) -> None:
    for node in _walk(nodes):
        if not node.number or node.number not in headings:
            continue
        occurrences = headings[node.number]
        printed = node.page_start
        page, title = min(occurrences, key=lambda item: (abs(item[0] - printed), item[0] < printed))
        node.page_start = page
        # Body headings are sometimes only the first visual line of a wrapped title.
        if title and len(title) > len(node.title):
            node.title = title


def _apply_page_ends(nodes: list[OutlineNode], max_page: int) -> None:
    ordered = _walk(nodes)
    for index, node in enumerate(ordered):
        end = node.page_start
        for nxt in ordered[index + 1 :]:
            if node.number and nxt.number and nxt.number.startswith(node.number + "."):
                end = max(end, nxt.page_start)
                continue
            end = max(end, nxt.page_start)
            break
        else:
            end = max(end, max_page)
        node.page_end = end


def _assign_blocks(nodes: list[OutlineNode], blocks: list[SourceBlock]) -> None:
    by_number: dict[str, OutlineNode] = {}
    for node in _walk(nodes):
        if node.number and node.number not in by_number:
            by_number[node.number] = node
    for block in blocks:
        if not block.section_path:
            continue
        last = block.section_path.split(" > ")[-1]
        match = SECTION_START_RE.match(last)
        if match is None:
            continue
        node = by_number.get(match.group(1))
        if node is not None:
            node.block_ids.append(block.id)


def build_document_outline(pdf_path: Path, source_index: SourceIndex) -> DocumentOutline:
    doc = fitz.open(pdf_path)
    try:
        rows = coalesced_lines(doc)
    finally:
        doc.close()

    lines_by_page: dict[int, list[str]] = {}
    for page, text in rows:
        lines_by_page.setdefault(page, []).append(text)

    toc_pages = _toc_pages(lines_by_page)
    entries: list[_TocEntry] = []
    for page in toc_pages:
        entries.extend(_entries_on_page(lines_by_page.get(page, [])))

    numbered = [entry for entry in entries if entry.number]
    if len(numbered) < MIN_NUMBERED_TOC_ENTRIES:
        return DocumentOutline(index_version=source_index.index_version, toc_pages=toc_pages, nodes=[])

    nodes = _build_tree(entries)
    _apply_body_pages(nodes, _body_headings(lines_by_page, set(toc_pages)))
    max_page = max((block.page for block in source_index.blocks), default=1)
    _apply_page_ends(nodes, max_page)
    _assign_blocks(nodes, source_index.blocks)
    return DocumentOutline(index_version=source_index.index_version, toc_pages=toc_pages, nodes=nodes)


def _all_nodes(outline: DocumentOutline) -> list[OutlineNode]:
    return _walk(outline.nodes)


def _nodes_for_phrases(
    outline: DocumentOutline,
    phrases: tuple[str, ...],
    *,
    match_any: bool,
) -> list[OutlineNode]:
    nodes = _all_nodes(outline)
    if match_any:
        hits: list[OutlineNode] = []
        for phrase in phrases:
            for node in nodes:
                if phrase in node.title.lower() and node not in hits:
                    hits.append(node)
        return hits
    for phrase in sorted(phrases, key=len, reverse=True):
        hits = [node for node in nodes if phrase in node.title.lower()]
        if hits:
            return hits
    return []


def _collect_ids(node: OutlineNode) -> list[str]:
    ids = list(node.block_ids)
    for child in node.children:
        ids.extend(_collect_ids(child))
    return ids


def select_outline_blocks(
    outline: DocumentOutline,
    blocks: list[SourceBlock],
    section_key: str,
) -> OutlineSelection:
    phrase_groups = EXTRACTION_NODE_PHRASES.get(section_key)
    if not phrase_groups or not outline.nodes:
        return OutlineSelection(blocks=[], labels=[])

    by_id = {block.id: block for block in blocks}
    chosen: list[OutlineNode] = []
    for phrases in phrase_groups:
        for node in _nodes_for_phrases(
            outline,
            phrases,
            match_any=section_key in MATCH_ANY_SECTIONS,
        ):
            if node not in chosen:
                chosen.append(node)
    if not chosen:
        return OutlineSelection(blocks=[], labels=[])

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for node in chosen:
        for block_id in _collect_ids(node):
            if block_id not in seen and block_id in by_id:
                seen.add(block_id)
                ordered_ids.append(block_id)

    reading_order = {block.id: position for position, block in enumerate(blocks)}
    selected = [by_id[block_id] for block_id in ordered_ids]
    selected.sort(key=lambda block: reading_order[block.id])
    labels = [f"{node.number} {node.title}".strip() if node.number else node.title for node in chosen]
    return OutlineSelection(blocks=selected, labels=labels)
