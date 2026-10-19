import numpy as np

from app.block_retrieval import select_field_blocks
from app.hybrid_search import HybridIndex, reciprocal_rank_fusion, tokenize
from app.schemas import SourceBlock


def _block(pid: str, page: int, text: str, section: str | None = None) -> SourceBlock:
    return SourceBlock(id=pid, page=page, bbox=[0, 0, 10, 10], text=text, section_path=section)


def _select(index, key, outline=(), vector=None, budget=5000, extra=6, min_blocks=1):
    return select_field_blocks(index, key, vector, list(outline), ["outline"] if outline else [], budget, 500, extra, min_blocks)


def test_tokenizer_keeps_section_numbers_and_greek_letters():
    assert tokenize("Section 5.1: β-hCG test for WOCBP") == ["5.1", "β-hcg", "test", "wocbp"]


def test_rrf_rewards_blocks_found_by_both_rankings():
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 4, 1]])

    assert max(fused, key=fused.get) in (1, 3)
    assert fused[1] > fused[2] and fused[3] > fused[4]


def test_keyword_retrieval_without_vectors_prefers_matching_blocks():
    index = HybridIndex(
        [
            _block("p1_b0", 1, "Introduction to the trial."),
            _block("p2_b0", 2, "Primary objective: assess efficacy."),
            _block("p3_b0", 3, "Inclusion criteria: age 18+."),
        ],
        None,
    )

    selection = _select(index, "study_objectives")

    assert "p2_b0" in [b.id for b in selection.blocks]
    assert not selection.semantic


def test_semantic_side_finds_block_without_shared_keywords():
    blocks = [
        _block("p10_b0", 10, "Participants who are breastfeeding cannot take part.", "5.2 Ineligibility"),
        _block("p11_b0", 11, "The trial site address and contact details.", "10 Administrative"),
    ]
    index = HybridIndex(blocks, np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32))

    selection = _select(index, "exclusion_criteria", vector=[0.9, 0.1], budget=150)

    assert [b.id for b in selection.blocks] == ["p10_b0"]
    assert selection.semantic


def test_outline_blocks_kept_and_extras_added_in_reading_order():
    blocks = [
        _block("p5_b0", 5, "Synopsis: the primary objective is to estimate efficacy.", "1.1 Synopsis"),
        _block("p20_b0", 20, "Background of the disease.", "2 Introduction"),
        _block("p30_b0", 30, "Objectives table follows.", "3 Objectives and Endpoints"),
        _block("p30_b1", 30, "Secondary objective: safety.", "3 Objectives and Endpoints"),
    ]
    index = HybridIndex(blocks, None)

    selection = _select(index, "study_objectives", outline=blocks[2:], extra=1)

    assert [b.id for b in selection.blocks] == ["p5_b0", "p30_b0", "p30_b1"]
    assert (selection.outline_blocks, selection.extra_blocks) == (2, 1)


def test_criteria_fields_use_only_the_outline_section():
    blocks = [
        _block("p6_b0", 6, "Synopsis inclusion criteria: adults aged 18 or older.", "1.1 Synopsis"),
        _block("p39_b0", 39, "1 Adult, 18 years or older at consent.", "5.1 Inclusion Criteria"),
    ]
    index = HybridIndex(blocks, None)

    selection = _select(index, "inclusion_criteria", outline=blocks[1:])

    assert [b.id for b in selection.blocks] == ["p39_b0"]


def test_amendment_table_pages_are_never_sent():
    blocks = [
        _block("p39_b0", 39, "1 Adult, 18 years or older at consent.", "5.1 Inclusion Criteria"),
        _block("p127_b0", 127, "Section # and Name\nDescription of Change\nBrief Rationale", "5.1 Inclusion Criteria"),
        _block("p127_b1", 127, "Revised criterion 1 to include adolescents", "5.1 Inclusion Criteria"),
    ]
    index = HybridIndex(blocks, None)

    assert [b.id for b in _select(index, "inclusion_criteria", outline=blocks).blocks] == ["p39_b0"]
    assert [b.id for b in _select(index, "inclusion_criteria").blocks] == ["p39_b0"]


def test_outline_overflow_keeps_best_ranked_blocks():
    filler = [_block(f"p40_b{i}", 40, "Generic narrative text " * 20, "8 Assessments") for i in range(5)]
    key = _block("p41_b0", 41, "Vital signs and physical examination are performed at each visit.", "8 Assessments")
    index = HybridIndex([*filler, key], None)

    selection = _select(index, "key_assessments_and_procedures", outline=[*filler, key], budget=900, extra=0)

    assert "p41_b0" in [b.id for b in selection.blocks]
    assert len(selection.blocks) < 6


def test_retrieval_respects_char_budget():
    index = HybridIndex([_block(f"p1_b{i}", 1, "endpoint " * 100) for i in range(20)], None)

    selection = _select(index, "endpoints", budget=3000, min_blocks=2)

    assert 2 <= len(selection.blocks) < 20
