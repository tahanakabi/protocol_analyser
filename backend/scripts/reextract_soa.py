"""Re-run only the schedule-of-activities extraction for stored documents.

Usage (from backend/):
    python -m scripts.reextract_soa <document_id> [document_id ...]
    python -m scripts.reextract_soa --all
"""

from __future__ import annotations

import argparse
import logging

from app.compose import compose_protocol_from_sections
from app.config import settings
from app.extract import _call_structured
from app.pdf_outline import build_document_outline
from app.pdf_tables import extract_tables_from_pdf
from app.section_storage import set_section_status, write_section_payload
from app.schemas import SectionStatus
from app.soa_extract import extract_schedule_of_activities
from app.storage import (
    pdf_path,
    read_document_outline,
    read_source_index,
    write_document_outline,
    write_tables_raw,
)
from app.validate import build_validation_summary


def reextract(document_id: str) -> None:
    path = pdf_path(document_id)
    doc_dir = path.parent
    source_index = read_source_index(document_id)
    if source_index is None:
        print(f"{document_id}: no source index, upload it again instead")
        return
    outline = read_document_outline(document_id)
    if outline is None or outline.index_version != source_index.index_version:
        outline = build_document_outline(path, source_index)
        write_document_outline(document_id, outline)
    max_page = max((b.page for b in source_index.blocks), default=0)

    tables = extract_tables_from_pdf(path)
    write_tables_raw(document_id, tables)
    set_section_status(doc_dir, "schedule_of_activities", SectionStatus.processing)
    soa = extract_schedule_of_activities(path, outline, tables, max_page, _call_structured)
    write_section_payload(doc_dir, "schedule_of_activities", soa)
    set_section_status(doc_dir, "schedule_of_activities", SectionStatus.completed)
    write_section_payload(doc_dir, "validation", build_validation_summary(compose_protocol_from_sections(doc_dir)))

    activities = sum(len(s.activities) for s in soa.schedules)
    print(
        f"{document_id}: {len(soa.schedules)} schedules, {activities} activities, "
        f"pages {soa.source_pages}, confidence {soa.confidence.value}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document_ids", nargs="*")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    ids = args.document_ids
    if args.all:
        ids = sorted(p.name for p in (settings.storage_dir / "documents").iterdir() if p.is_dir())
    for document_id in ids:
        reextract(document_id)


if __name__ == "__main__":
    main()
