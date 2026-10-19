from app.schemas import SourcedTextLLM, SourceBlock, SourceIndex
from app.validate import quote_matches_block, validate_sourced_text


def test_quote_matches_block_substring():
    block = SourceBlock(id="p1_b0", page=1, bbox=[0, 0, 100, 20], text="Primary objective: assess safety.")
    assert quote_matches_block("assess safety", block.text)


def test_validate_invalid_missing_ids():
    block_index = {
        "p1_b0": SourceBlock(id="p1_b0", page=1, bbox=[0, 0, 10, 10], text="Inclusion: age 18+")
    }
    raw = SourcedTextLLM(text="age 18+", source_block_ids=[], evidence_quotes=[])
    result = validate_sourced_text(raw, block_index)
    assert result.evidence_valid is False


def test_validate_valid_citation():
    block_index = {
        "p2_b3": SourceBlock(id="p2_b3", page=2, bbox=[72, 100, 400, 120], text="Exclusion: pregnancy")
    }
    raw = SourcedTextLLM(
        text="pregnancy",
        source_block_ids=["p2_b3"],
        evidence_quotes=["pregnancy"],
    )
    result = validate_sourced_text(raw, block_index)
    assert result.evidence_valid is True
    assert result.sources[0].page == 2
    assert result.sources[0].quote_matched is True
