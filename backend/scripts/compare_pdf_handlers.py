"""Parse one stored document with several PDF handlers and compare what extraction would see.

Usage (from backend/):
    python -m scripts.compare_pdf_handlers <document_id> [handler ...] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from app.pdf_handlers import HANDLERS
from app.pdf_outline import EXTRACTION_NODE_PHRASES, build_document_outline, select_outline_blocks
from app.pdf_source import parse_pdf_blocks
from app.storage import pdf_path, read_meta


def _summary(handler_id: str, source_index, outline, seconds: float) -> dict:
    blocks = source_index.blocks
    return {
        "handler": handler_id,
        "seconds": round(seconds, 1),
        "blocks": len(blocks),
        "median_chars": int(statistics.median(len(b.text) for b in blocks)) if blocks else 0,
        "with_section_path": sum(1 for b in blocks if b.section_path),
        "distinct_sections": len({b.section_path for b in blocks if b.section_path}),
        "total_chars": sum(len(b.text) for b in blocks),
        "outline_fields": {
            key: len(select_outline_blocks(outline, blocks, key).blocks) for key in EXTRACTION_NODE_PHRASES
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("document_id")
    parser.add_argument("handlers", nargs="*", default=list(HANDLERS))
    parser.add_argument("--out", type=Path, default=Path("storage/handler_comparison"))
    args = parser.parse_args()

    meta = read_meta(args.document_id)
    if meta is None:
        raise SystemExit(f"Unknown document {args.document_id}")
    path = pdf_path(args.document_id)
    args.out.mkdir(parents=True, exist_ok=True)

    for handler_id in args.handlers:
        reason = HANDLERS[handler_id].unavailable_reason()
        if reason:
            print(json.dumps({"handler": handler_id, "skipped": reason}))
            continue
        started = time.perf_counter()
        source_index = parse_pdf_blocks(path, meta.sha256, handler_id)
        seconds = time.perf_counter() - started
        outline = build_document_outline(path, source_index)
        (args.out / f"{handler_id}.source_index.json").write_text(source_index.model_dump_json(indent=1))
        summary = _summary(handler_id, source_index, outline, seconds)
        (args.out / f"{handler_id}.summary.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
