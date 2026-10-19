from app.block_merge import merge_small_blocks
from app.schemas import SourceBlock


def _block(index: int, text: str, section: str | None, page: int = 1) -> SourceBlock:
    return SourceBlock(
        id=f"p{page}_b{index}",
        page=page,
        bbox=[10.0, 10.0 * index, 100.0, 10.0 * index + 8],
        text=text,
        section_path=section,
    )


def test_small_blocks_in_same_section_are_joined():
    blocks = [
        _block(0, "a" * 50, "5.1 Inclusion"),
        _block(1, "b" * 60, "5.1 Inclusion"),
        _block(2, "c" * 300, "5.2 Exclusion"),
    ]

    merged = merge_small_blocks(blocks, min_chars=100, max_chars=1000)

    assert [b.text for b in merged] == ["a" * 50 + "\n" + "b" * 60, "c" * 300]
    assert merged[0].bbox == [10.0, 0.0, 100.0, 18.0]
    assert [b.id for b in merged] == ["p1_b0", "p1_b1"]


def test_small_block_never_crosses_into_another_section():
    blocks = [_block(0, "a" * 50, "5.1 Inclusion"), _block(1, "b" * 50, "5.2 Exclusion")]

    assert len(merge_small_blocks(blocks, min_chars=100, max_chars=1000)) == 2


def test_sectionless_blocks_absorb_neighbours_until_big_enough():
    blocks = [
        _block(0, "x" * 30, None),
        _block(1, "y" * 30, None),
        _block(2, "z" * 80, "6 Treatment"),
        _block(3, "w" * 300, "6 Treatment"),
    ]

    merged = merge_small_blocks(blocks, min_chars=100, max_chars=1000)

    assert merged[0].text == "\n".join(["x" * 30, "y" * 30, "z" * 80])
    assert merged[0].section_path == "6 Treatment"
    assert merged[1].text == "w" * 300


def test_merge_respects_page_and_size_limits():
    blocks = [
        _block(0, "a" * 50, "8 Assessments", page=1),
        _block(0, "b" * 50, "8 Assessments", page=2),
        _block(1, "c" * 980, "8 Assessments", page=2),
    ]

    merged = merge_small_blocks(blocks, min_chars=100, max_chars=1000)

    assert [(b.page, len(b.text)) for b in merged] == [(1, 50), (2, 50), (2, 980)]
