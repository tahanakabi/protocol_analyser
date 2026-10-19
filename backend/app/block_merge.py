"""Merge small source blocks into larger ones after any PDF handler has run.

Rules, applied in reading order:

- A block shorter than ``min_chars`` joins its neighbour when both have the same ``section_path``.
- A short block with no section joins its neighbours, whatever their section, until it reaches ``min_chars``;
  the merged block takes the neighbour's section.
- Blocks only merge on the same page (a block has a single page and bounding box) and never past
  ``max_chars``.
"""

from __future__ import annotations

from app.schemas import SourceBlock

MIN_BLOCK_CHARS = 200
MAX_BLOCK_CHARS = 1500


def _union_bbox(a: list[float], b: list[float]) -> list[float]:
    if len(a) < 4:
        return list(b)
    if len(b) < 4:
        return list(a)
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _can_merge(left: SourceBlock, right: SourceBlock, min_chars: int, max_chars: int) -> bool:
    if left.page != right.page:
        return False
    if len(left.text) + len(right.text) + 1 > max_chars:
        return False
    left_small = len(left.text) < min_chars
    right_small = len(right.text) < min_chars
    if left.section_path == right.section_path:
        return left_small or right_small
    return (left_small and left.section_path is None) or (right_small and right.section_path is None)


def _join(left: SourceBlock, right: SourceBlock) -> SourceBlock:
    return SourceBlock(
        id=left.id,
        page=left.page,
        bbox=_union_bbox(left.bbox, right.bbox),
        text=f"{left.text}\n{right.text}",
        section_path=left.section_path or right.section_path,
    )


def _renumber(blocks: list[SourceBlock]) -> list[SourceBlock]:
    counters: dict[int, int] = {}
    out = []
    for block in blocks:
        index = counters.get(block.page, 0)
        counters[block.page] = index + 1
        out.append(block.model_copy(update={"id": f"p{block.page}_b{index}"}))
    return out


def merge_small_blocks(
    blocks: list[SourceBlock],
    min_chars: int = MIN_BLOCK_CHARS,
    max_chars: int = MAX_BLOCK_CHARS,
) -> list[SourceBlock]:
    merged: list[SourceBlock] = []
    for block in blocks:
        if merged and _can_merge(merged[-1], block, min_chars, max_chars):
            merged[-1] = _join(merged[-1], block)
        else:
            merged.append(block)
    return _renumber(merged)
