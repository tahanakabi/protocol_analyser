"""Choose the source blocks sent to the LLM for each extraction field.

Every field is ranked with hybrid search (BM25 on its keyword query + embedding similarity to its
description, fused by reciprocal rank). The table-of-contents outline still decides *where* the field
lives when it can:

- Outline match: all blocks of the matched sections are kept if they fit the budget; if not, the
  best-ranked ones are kept. Then up to ``extra_blocks`` top-ranked blocks from elsewhere that both
  keyword and semantic search found are added (synopsis, appendices, a section the outline titled
  differently), except for criteria lists.
- No outline match: the top-ranked blocks fill the budget.

Blocks are always sent in reading order so numbered lists stay in sequence.
"""

import json
import re
from dataclasses import dataclass

from app.hybrid_search import HybridIndex
from app.schemas import SourceBlock


@dataclass(frozen=True)
class FieldQuery:
    keywords: str
    description: str


FIELD_QUERIES: dict[str, FieldQuery] = {
    "study_objectives": FieldQuery(
        "primary objective secondary objective study objectives purpose synopsis",
        "Primary and secondary objectives of the clinical study: what the trial aims to demonstrate or evaluate.",
    ),
    "endpoints": FieldQuery(
        "primary endpoint secondary endpoint exploratory endpoint efficacy endpoint outcome measure",
        "Primary, secondary and exploratory endpoints: the outcome measures used to evaluate efficacy, "
        "safety and immunogenicity.",
    ),
    "inclusion_criteria": FieldQuery(
        "inclusion criteria criterion eligible 5.1",
        "Inclusion criteria: the conditions a participant must meet to be eligible to enrol in the study.",
    ),
    "exclusion_criteria": FieldQuery(
        "exclusion criteria criterion excluded 5.2",
        "Exclusion criteria: conditions or history that make a participant ineligible to enrol.",
    ),
    "visits": FieldQuery(
        "visit day window screening follow-up schedule telephone",
        "Study visits and their timing: screening, dosing and follow-up visits, study days and visit windows.",
    ),
    "key_assessments_and_procedures": FieldQuery(
        "assessments procedures laboratory vital signs physical examination sample collection immunogenicity",
        "Study assessments and procedures performed on participants: physical examinations, vital signs, "
        "laboratory tests, sample collection, efficacy and immunogenicity assessments.",
    ),
    "safety_monitoring_rules": FieldQuery(
        "safety monitoring adverse event serious AESI stopping rule data monitoring committee DSMB reporting",
        "Safety monitoring: adverse event and serious adverse event reporting, events of special interest, "
        "stopping rules and data safety monitoring board oversight.",
    ),
}


# Numbered lists: the outline section is the complete list, and synopsis copies would add duplicates.
OUTLINE_ONLY_FIELDS = frozenset({"inclusion_criteria", "exclusion_criteria"})

# Amendment "summary of changes" tables describe past versions of objectives, endpoints and criteria,
# and their section-name cells put them inside outline sections. Their column header repeats on every
# page, so whole pages are skipped for field extraction; otherwise the model extracts superseded text.
AMENDMENT_TABLE_RE = re.compile(r"non-substantial|description of change|brief rationale", re.IGNORECASE)


def amendment_pages(blocks: list[SourceBlock]) -> set[int]:
    return {block.page for block in blocks if AMENDMENT_TABLE_RE.search(block.text)}


def _compact_block_dict(block: SourceBlock, max_text_chars: int) -> dict:
    text = block.text
    if len(text) > max_text_chars:
        text = text[: max_text_chars - 1] + "…"
    row: dict = {"id": block.id, "p": block.page, "t": text}
    if block.section_path:
        row["section"] = block.section_path
    return row


def _row_size(row: dict) -> int:
    return len(json.dumps(row, ensure_ascii=False, separators=(",", ":"))) + 1


@dataclass
class FieldSelection:
    blocks: list[SourceBlock]
    outline_labels: list[str]
    outline_blocks: int
    extra_blocks: int
    semantic: bool


class _Packer:
    def __init__(self, char_budget: int, max_block_text_chars: int) -> None:
        self.char_budget = char_budget
        self.max_block_text_chars = max_block_text_chars
        self.used = 2
        self.ids: set[str] = set()
        self.blocks: list[SourceBlock] = []

    def add(self, block: SourceBlock) -> bool:
        if block.id in self.ids:
            return False
        size = _row_size(_compact_block_dict(block, self.max_block_text_chars))
        if self.blocks and self.used + size > self.char_budget:
            return False
        self.used += size
        self.ids.add(block.id)
        self.blocks.append(block)
        return True


def select_field_blocks(
    index: HybridIndex,
    section_key: str,
    query_vector: list[float] | None,
    outline_blocks: list[SourceBlock],
    outline_labels: list[str],
    char_budget: int,
    max_block_text_chars: int,
    extra_blocks: int,
    min_blocks: int = 6,
    exclude_pages: frozenset[int] = frozenset(),
) -> FieldSelection:
    query = FIELD_QUERIES.get(section_key)
    skip_pages = amendment_pages(index.blocks) | exclude_pages
    ranked = [
        hit
        for hit in index.search(query.keywords if query else section_key, query_vector)
        if hit.block.page not in skip_pages
    ]
    outline_blocks = [b for b in outline_blocks if b.page not in skip_pages]
    rank = {hit.block.id: position for position, hit in enumerate(ranked)}
    reading_order = {block.id: position for position, block in enumerate(index.blocks)}
    packer = _Packer(char_budget, max_block_text_chars)

    if outline_blocks:
        for block in sorted(outline_blocks, key=lambda b: (rank.get(b.id, len(rank)), reading_order.get(b.id, 0))):
            packer.add(block)
        from_outline = len(packer.blocks)
        outline_ids = {b.id for b in outline_blocks}
        limit = 0 if section_key in OUTLINE_ONLY_FIELDS else extra_blocks
        # Extras need agreement: with both rankings available, only blocks found by both are added.
        agreed = [h for h in ranked if h.keyword_rank and (h.semantic_rank or query_vector is None)]
        added = 0
        for hit in agreed:
            if added >= limit:
                break
            if hit.block.id not in outline_ids and packer.add(hit.block):
                added += 1
    else:
        from_outline = 0
        for hit in ranked:
            packer.add(hit.block)
        if len(packer.blocks) < min_blocks:
            for block in index.blocks:
                if len(packer.blocks) >= min_blocks:
                    break
                if block.page not in skip_pages:
                    packer.add(block)
        added = len(packer.blocks)

    selected = sorted(packer.blocks, key=lambda b: reading_order.get(b.id, 0))
    return FieldSelection(
        blocks=selected,
        outline_labels=outline_labels,
        outline_blocks=from_outline,
        extra_blocks=added,
        semantic=index.has_vectors and query_vector is not None,
    )


def format_field_context(selection: FieldSelection, section_key: str, max_block_text_chars: int) -> str:
    rows = [_compact_block_dict(block, max_block_text_chars) for block in selection.blocks]
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    retrieval = "hybrid" if selection.semantic else "keyword"
    outline = "; ".join(selection.outline_labels) or "none"
    meta = (
        f"section={section_key}; outline={outline}; {selection.outline_blocks} outline blocks + "
        f"{selection.extra_blocks} {retrieval}-retrieved blocks; ~{len(payload)} chars. "
        "Fields: id, p=page, section=heading path, t=text."
    )
    return f"{meta}\n\n{payload}"
