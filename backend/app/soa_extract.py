"""Schedule of Activities: every SoA table as structured JSON plus a complete text summary.

Each page's table goes to the LLM as pipe-separated rows, so column positions map marks to visits.
The page text outside the table (caption, footnotes, abbreviations) goes with it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import fitz

from app.pdf_block_builder import HEADER_BAND
from app.pdf_outline import _all_nodes
from app.schemas import (
    DocumentOutline,
    RawTableGrid,
    ScheduleOfActivities,
    SoaActivity,
    SoaConfidence,
    SoaExtractionLLM,
    SoaSchedule,
    TablesRawPayload,
)

logger = logging.getLogger(__name__)

SOA_TITLE_PHRASES = ("schedule of activities", "schedule of assessments", "schedule of events")
CAPTION_RE = re.compile(r"^\s*Table\s+\d+[A-Za-z]?\b", re.IGNORECASE)
SCHEDULE_RE = re.compile(r"schedule\s+of\s+(activities|assessments|events)", re.IGNORECASE)
MAX_PARALLEL_CALLS = 4

SOA_SYSTEM = """You convert Schedule of Activities tables from a clinical trial protocol into JSON.
Input, per page: the page text outside the table (caption, footnotes, abbreviations), then the table as
pipe-separated rows in which each column position is the same column on every row.
Rules:
- One schedule per distinct table (Table 1, Table 2, ...). A page whose table repeats the previous header
  rows is a continuation: merge its rows into the same schedule.
- visits: one entry per visit column, left to right. Combine the header rows (Day, Week, Window,
  Site Visit / Home Collection, ...) into label, timing, window and visit_type. Labels must be unique
  and carry no footnote markers, e.g. "Day 8" for a header printed "8 a" under "Day".
- occurrence.visit must be copied exactly from one of the visit labels.
- activities: every procedure row, in order; never skip or summarise rows. A row with text only in the
  first column is a category header: set it as category on the rows below instead of emitting it.
- occurrences: one per visit column whose cell is marked (X or any text), matched by column position.
  Cell text other than a bare X goes in detail (e.g. "predose"). Prose spanning several visit columns
  goes in note instead.
- Footnote markers (letters or symbols after a name, header or cell) must be resolved to the footnote
  text and attached to that visit or activity; also list every footnote under footnotes.
- Copy names and text as printed; only drop footnote markers from names.
- section_reference comes from the "For details see Section" column.
- page is the page number where the activity row is printed."""


@dataclass
class SoaPage:
    page: int
    outside_text: str
    grids: list[RawTableGrid] = field(default_factory=list)

    def prompt(self) -> str:
        parts = [f"=== Page {self.page} ===", "Text outside the table:", self.outside_text or "(none)"]
        for index, grid in enumerate(self.grids, start=1):
            parts.append(f"Table grid {index}:")
            parts.extend(
                "| " + " | ".join(" ".join((cell.raw or "").split()) for cell in row) + " |" for row in grid.rows
            )
        return "\n".join(parts)

    @property
    def caption(self) -> str | None:
        """'table 2' when the page carries a Schedule of Activities caption."""
        if not SCHEDULE_RE.search(self.outside_text):
            return None
        for line in self.outside_text.splitlines():
            match = CAPTION_RE.match(line)
            if match:
                return " ".join(match.group(0).lower().split())
        return None


def soa_pages(outline: DocumentOutline | None, tables: TablesRawPayload) -> list[int]:
    """Pages of the SoA section from the contents list; keyword-detected pages when there is no match."""
    grid_pages = {grid.page_number for grid in tables.tables}
    pages: set[int] = set()
    if outline is not None:
        for node in _all_nodes(outline):
            if any(phrase in node.title.lower() for phrase in SOA_TITLE_PHRASES):
                pages.update(range(node.page_start, node.page_end + 1))
    pages &= grid_pages
    if not pages:
        pages = set(tables.soa_candidate_pages)
    return sorted(pages)


def _inside(line_bbox, rects: list[fitz.Rect]) -> bool:
    center = fitz.Point((line_bbox[0] + line_bbox[2]) / 2, (line_bbox[1] + line_bbox[3]) / 2)
    return any(rect.contains(center) for rect in rects)


def build_soa_pages(pdf_path: Path, pages: list[int], tables: TablesRawPayload) -> list[SoaPage]:
    grids_by_page: dict[int, list[RawTableGrid]] = {}
    for grid in tables.tables:
        grids_by_page.setdefault(grid.page_number, []).append(grid)

    result: list[SoaPage] = []
    doc = fitz.open(pdf_path)
    try:
        for page_number in pages:
            page = doc[page_number - 1]
            grids = grids_by_page.get(page_number, [])
            rects = [fitz.Rect(grid.bbox) for grid in grids if grid.bbox]
            outside: list[str] = []
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    text = "".join(span["text"] for span in line["spans"]).strip()
                    if not text or line["bbox"][1] < HEADER_BAND or _inside(line["bbox"], rects):
                        continue
                    outside.append(text)
            if not grids:
                # No table geometry: the whole page text is all the model gets.
                outside = [line for line in page.get_text("text").splitlines() if line.strip()]
            result.append(SoaPage(page_number, "\n".join(outside), grids))
    finally:
        doc.close()
    return result


def group_pages(pages: list[SoaPage]) -> list[list[SoaPage]]:
    """One group per table. Continuation pages repeat the caption or have none; footnotes are often on the last page."""
    groups: list[list[SoaPage]] = []
    current: str | None = None
    for page in pages:
        caption = page.caption
        if not groups or (caption is not None and caption != current):
            groups.append([page])
            current = caption
        else:
            groups[-1].append(page)
    return groups


_MARKER_SUFFIX_RE = re.compile(r"\s+([a-z]{1,2}|[*†‡§¶#]+)$")
_MARKER_PREFIX_RE = re.compile(r"^([a-z]{1,2}|[*†‡§¶#]+)\s+")
_VISIT_PREFIX_RE = re.compile(r"^(day|week|visit|month|v)")


def _strip_marker(text: str, markers: set[str]) -> str:
    match = _MARKER_SUFFIX_RE.search(text)
    return text[: match.start()] if match and match.group(1) in markers else text


def _strip_marker_prefix(text: str, markers: set[str]) -> str:
    match = _MARKER_PREFIX_RE.match(text)
    return text[match.end() :] if match and match.group(1) in markers else text


def _visit_key(label: str) -> str:
    return _VISIT_PREFIX_RE.sub("", _normalized(label))


def _table_key(label: str | None) -> str:
    match = CAPTION_RE.match(label or "")
    return " ".join(match.group(0).lower().split()) if match else (label or "").strip().lower()


def clean_schedule(schedule: SoaSchedule) -> None:
    """Undo common model slips: footnote letters left on names, category rows emitted as activities,
    and occurrences that name a visit slightly differently from its column label."""
    markers = {f.marker.strip() for f in schedule.footnotes if f.marker.strip()}
    for footnote in schedule.footnotes:
        footnote.text = _strip_marker_prefix(footnote.text, markers)
    for visit in schedule.visits:
        visit.label = _strip_marker(visit.label, markers)
        visit.notes = [_strip_marker_prefix(note, markers) for note in visit.notes]

    labels = {visit.label for visit in schedule.visits}
    by_key: dict[str, str] = {}
    for label in labels:
        by_key.setdefault(_visit_key(label), label)

    categories = {a.category.strip().lower() for a in schedule.activities if a.category}
    kept: list[SoaActivity] = []
    for activity in schedule.activities:
        activity.name = _strip_marker(activity.name, markers)
        activity.footnotes = [_strip_marker_prefix(note, markers) for note in activity.footnotes]
        is_category_row = (
            activity.name.strip().lower() in categories
            and not activity.occurrences
            and not activity.note
            and not activity.section_reference
        )
        if is_category_row:
            continue
        for occurrence in activity.occurrences:
            visit = _strip_marker(occurrence.visit, markers)
            occurrence.visit = visit if visit in labels else by_key.get(_visit_key(visit), visit)
        kept.append(activity)
    schedule.activities = kept


_NORMALIZE_RE = re.compile(r"[^0-9a-z]+")


def _normalized(text: str) -> str:
    return _NORMALIZE_RE.sub("", text.lower())


def _locate(page: fitz.Page, name: str) -> list[float] | None:
    words = name.split()
    for probe in (name, " ".join(words[:4]), " ".join(words[:2])):
        if probe:
            hits = page.search_for(probe)
            if hits:
                return [float(v) for v in hits[0]]
    return None


def validate_schedules(pdf_path: Path, schedules: list[SoaSchedule]) -> None:
    """Check each activity is printed on its page, record where, and flag occurrences of unknown visits."""
    doc = fitz.open(pdf_path)
    try:
        page_text = {i + 1: _normalized(doc[i].get_text("text")) for i in range(len(doc))}
        for schedule in schedules:
            labels = {visit.label for visit in schedule.visits}
            for activity in schedule.activities:
                pages = [activity.page, *schedule.pages]
                found = next((p for p in pages if _normalized(activity.name) in page_text.get(p, "")), None)
                activity.found_on_page = found is not None
                if found is not None:
                    activity.page = found
                    activity.bbox = _locate(doc[found - 1], activity.name)
                activity.unknown_visits = [o.visit for o in activity.occurrences if o.visit not in labels]
    finally:
        doc.close()


def _visit_line(visit) -> str:
    timing = visit.timing if visit.timing and _normalized(visit.timing) != _normalized(visit.label) else None
    details = [d for d in (timing, f"window {visit.window}" if visit.window else None, visit.visit_type) if d]
    line = f"- {visit.label}"
    if details:
        line += f" ({'; '.join(details)})"
    if visit.notes:
        line += " — " + " ".join(visit.notes)
    return line


def _activity_line(activity: SoaActivity) -> str:
    when = ", ".join(f"{o.visit} ({o.detail})" if o.detail else o.visit for o in activity.occurrences)
    parts = [when] if when else []
    if activity.note:
        parts.append(activity.note)
    line = f"- {activity.name}: " + ("; ".join(parts) if parts else "no visit cell marked in the table")
    if activity.section_reference:
        line += f" [Section {activity.section_reference}]"
    for note in activity.footnotes:
        line += f"\n  Note: {note}"
    return line


def soa_summary(schedules: list[SoaSchedule]) -> str:
    """Plain-text rendering of every schedule, visit, activity and footnote; nothing is dropped."""
    sections: list[str] = []
    for schedule in schedules:
        heading = " – ".join(part for part in (schedule.table_label, schedule.title) if part)
        lines = [heading]
        if schedule.population:
            lines.append(f"Applies to: {schedule.population}")
        if schedule.pages:
            lines.append(f"Pages: {', '.join(str(p) for p in schedule.pages)}")
        if schedule.visits:
            lines.append("Visits:")
            lines.extend(_visit_line(visit) for visit in schedule.visits)
        if schedule.activities:
            lines.append("Activities:")
            current: str | None = None
            for activity in schedule.activities:
                if activity.category and activity.category != current:
                    lines.append(f"{activity.category}:")
                current = activity.category
                lines.append(_activity_line(activity))
        if schedule.footnotes:
            lines.append("Footnotes:")
            lines.extend(f"- {f.marker}: {f.text}" for f in schedule.footnotes)
        if schedule.abbreviations:
            lines.append("Abbreviations: " + "; ".join(schedule.abbreviations))
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def merge_continuations(schedules: list[SoaSchedule]) -> list[SoaSchedule]:
    """Join schedules that share a table label (a table continued under a repeated caption)."""
    merged: list[SoaSchedule] = []
    by_label: dict[str, SoaSchedule] = {}
    for schedule in schedules:
        key = _table_key(schedule.table_label)
        first = by_label.get(key) if key else None
        if first is None:
            merged.append(schedule)
            if key:
                by_label[key] = schedule
            continue
        first.pages = sorted(set(first.pages) | set(schedule.pages))
        known = {visit.label for visit in first.visits}
        first.visits.extend(visit for visit in schedule.visits if visit.label not in known)
        first.activities.extend(schedule.activities)
        markers = {f.marker for f in first.footnotes}
        first.footnotes.extend(f for f in schedule.footnotes if f.marker not in markers)
        first.abbreviations.extend(a for a in schedule.abbreviations if a not in first.abbreviations)
    return merged


def extract_schedule_of_activities(
    pdf_path: Path,
    outline: DocumentOutline | None,
    tables: TablesRawPayload,
    max_page: int,
    call_llm: Callable[[str, str, type], SoaExtractionLLM],
) -> ScheduleOfActivities:
    pages = soa_pages(outline, tables)
    if not pages:
        return ScheduleOfActivities(notes="No Schedule of Activities pages found.", confidence=SoaConfidence.low)

    groups = group_pages(build_soa_pages(pdf_path, pages, tables))
    logger.info("SoA pages %s in %s table group(s)", pages, len(groups))

    def run(group: list[SoaPage]) -> list[SoaSchedule]:
        result = call_llm(SOA_SYSTEM, "\n\n".join(page.prompt() for page in group), SoaExtractionLLM)
        schedules = [SoaSchedule.model_validate(s.model_dump()) for s in result.schedules]
        if len(schedules) == 1:
            # A single table spans the whole group, footnote-only pages included.
            schedules[0].pages = sorted(set(schedules[0].pages) | {page.page for page in group})
        return schedules

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_CALLS) as pool:
        results = list(pool.map(run, groups))

    schedules = merge_continuations([schedule for group in results for schedule in group])
    for schedule in schedules:
        clean_schedule(schedule)
    validate_schedules(pdf_path, schedules)

    has_grids = all(page.grids for group in groups for page in group)
    activities = [a for s in schedules for a in s.activities]
    problems = []
    missing = [a.name for a in activities if not a.found_on_page]
    if missing:
        problems.append(f"{len(missing)} activities not found on their page: {', '.join(missing[:5])}")
    unknown = sorted({v for a in activities for v in a.unknown_visits})
    if unknown:
        problems.append(f"occurrences reference unknown visits: {', '.join(unknown[:5])}")
    bad_pages = [p for s in schedules for p in s.pages if p < 1 or p > max_page]
    if bad_pages:
        problems.append(f"page numbers outside the document: {bad_pages}")
    if not has_grids:
        problems.append("some pages had no table geometry; read from page text")

    structural_valid = bool(schedules) and not problems
    confidence = SoaConfidence.high if structural_valid else SoaConfidence.medium if has_grids else SoaConfidence.low
    return ScheduleOfActivities(
        schedules=schedules,
        summary=soa_summary(schedules),
        source_pages=pages,
        notes="; ".join(problems) or None,
        confidence=confidence,
        structural_valid=structural_valid,
    )
