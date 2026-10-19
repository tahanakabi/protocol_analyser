import re
from pathlib import Path

import fitz
import pdfplumber

from app.schemas import CellState, NormalizedCell, RawTableGrid, TablesRawPayload

SOA_KEYWORDS = re.compile(
    r"schedule\s+of\s+activities|study\s+procedures|\bsoa\b",
    re.IGNORECASE,
)

MARK_CHARS = frozenset("Xx✓✔☑•●")
DASH_ONLY = re.compile(r"^[\s\-–—]+$")


def normalize_cell(raw: str | None) -> NormalizedCell:
    if raw is None:
        return NormalizedCell(raw="", state=CellState.absent)
    stripped = raw.strip()
    if not stripped:
        return NormalizedCell(raw=raw, state=CellState.absent)
    if DASH_ONLY.match(stripped):
        return NormalizedCell(raw=raw, state=CellState.na)
    if len(stripped) == 1 and stripped in MARK_CHARS:
        return NormalizedCell(raw=raw, state=CellState.marked)
    if stripped.upper() == "X":
        return NormalizedCell(raw=raw, state=CellState.marked)
    return NormalizedCell(raw=raw, state=CellState.text, value=stripped)


def _grid_sparsity_score(rows: list[list[str]]) -> float:
    if not rows:
        return 0.0
    total = 0
    sparse = 0
    for row in rows:
        for cell in row:
            total += 1
            nc = normalize_cell(cell)
            if nc.state in (CellState.absent, CellState.marked, CellState.na):
                sparse += 1
    return sparse / total if total else 0.0


def _is_soa_like_table(rows: list[list[str]]) -> bool:
    if len(rows) < 2:
        return False
    col_count = max(len(r) for r in rows)
    if col_count < 3:
        return False
    return _grid_sparsity_score(rows) >= 0.45


def _normalize_grid(rows: list[list[str]]) -> list[list[NormalizedCell]]:
    return [[normalize_cell(c) for c in row] for row in rows]


def _extract_pymupdf_tables(page: fitz.Page, page_number: int) -> list[RawTableGrid]:
    grids: list[RawTableGrid] = []
    try:
        finder = page.find_tables()
    except Exception:
        return grids
    for table in finder.tables:
        try:
            data = table.extract()
        except Exception:
            continue
        if not data:
            continue
        string_rows = [[str(c) if c is not None else "" for c in row] for row in data]
        bbox = list(table.bbox) if hasattr(table, "bbox") else None
        grids.append(
            RawTableGrid(
                page_number=page_number,
                extractor="pymupdf",
                rows=_normalize_grid(string_rows),
                bbox=bbox,
            )
        )
    return grids


def _extract_pdfplumber_tables(
    pdf_path: Path, page_number: int, page_height: float
) -> list[RawTableGrid]:
    grids: list[RawTableGrid] = []
    with pdfplumber.open(pdf_path) as pdf:
        if page_number < 1 or page_number > len(pdf.pages):
            return grids
        page = pdf.pages[page_number - 1]
        try:
            tables = page.extract_tables() or []
        except Exception:
            return grids
        for table in tables:
            if not table:
                continue
            string_rows = [[str(c) if c is not None else "" for c in row] for row in table]
            grids.append(
                RawTableGrid(
                    page_number=page_number,
                    extractor="pdfplumber",
                    rows=_normalize_grid(string_rows),
                    bbox=None,
                )
            )
    return grids


def _page_has_soa_keyword(text: str) -> bool:
    return bool(SOA_KEYWORDS.search(text))


def _rows_from_grid(grid: RawTableGrid) -> list[list[str]]:
    return [[c.raw for c in row] for row in grid.rows]


def _jagged_or_empty(grid: RawTableGrid) -> bool:
    if not grid.rows:
        return True
    lengths = {len(r) for r in grid.rows}
    return len(lengths) > 1 and max(lengths) - min(lengths) > 2


def extract_tables_from_pdf(pdf_path: Path) -> TablesRawPayload:
    doc = fitz.open(pdf_path)
    all_tables: list[RawTableGrid] = []
    soa_candidate_pages: list[int] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_number = page_index + 1
        text = page.get_text("text")
        keyword_hit = _page_has_soa_keyword(text)

        pymupdf_grids = _extract_pymupdf_tables(page, page_number)
        page_tables: list[RawTableGrid] = list(pymupdf_grids)

        for g in pymupdf_grids:
            if _jagged_or_empty(g):
                plumber = _extract_pdfplumber_tables(pdf_path, page_number, page.rect.height)
                if plumber:
                    page_tables = plumber
                    break

        if not page_tables:
            plumber = _extract_pdfplumber_tables(pdf_path, page_number, page.rect.height)
            page_tables.extend(plumber)

        for grid in page_tables:
            raw_rows = _rows_from_grid(grid)
            if keyword_hit or _is_soa_like_table(raw_rows):
                if page_number not in soa_candidate_pages:
                    soa_candidate_pages.append(page_number)
            all_tables.append(grid)

    doc.close()

    if not soa_candidate_pages:
        for grid in all_tables:
            if _is_soa_like_table(_rows_from_grid(grid)):
                if grid.page_number not in soa_candidate_pages:
                    soa_candidate_pages.append(grid.page_number)

    return TablesRawPayload(tables=all_tables, soa_candidate_pages=soa_candidate_pages)
