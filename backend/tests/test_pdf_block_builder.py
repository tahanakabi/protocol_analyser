import tempfile
from pathlib import Path

import fitz

from app.pdf_block_builder import _heading_level, _update_section_stack
from app.pdf_source import SOURCE_INDEX_VERSION, parse_pdf_blocks


def test_heading_level_ignores_numbered_criteria():
    assert _heading_level("1 Adult, ≥ 18 years of age") is None
    assert _heading_level("5.1 Inclusion Criteria") == 2
    assert _heading_level("5 STUDY POPULATION") == 1


def test_section_stack_tracks_hierarchy():
    stack = ["4 STUDY DESIGN"]
    stack = _update_section_stack(stack, "4.1 Overall Design")
    assert stack == ["4 STUDY DESIGN", "4.1 Overall Design"]
    stack = _update_section_stack(stack, "5 STUDY POPULATION")
    assert stack == ["5 STUDY POPULATION"]


def test_merges_body_lines_and_attaches_section_path():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "criteria.pdf"
        doc = fitz.open()
        page = doc.new_page(width=500, height=700)
        page.insert_text((72, 120), "5.1 Inclusion Criteria", fontsize=14)
        page.insert_text((72, 160), "Participants are eligible only if all criteria apply:", fontsize=11)
        page.insert_text((72, 178), "1", fontsize=11)
        page.insert_text((90, 178), "Adult, ≥ 18 years of age at consent", fontsize=11)
        doc.save(pdf_path)
        doc.close()

        index = parse_pdf_blocks(pdf_path, "test-hash")
        assert index.index_version == SOURCE_INDEX_VERSION
        bodies = [b for b in index.blocks if "eligible" in b.text.lower() or "Adult" in b.text]
        assert bodies, "expected merged paragraph block(s)"
        assert any(b.section_path and "5.1 Inclusion Criteria" in b.section_path for b in bodies)


def test_skips_repeating_header():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "header.pdf"
        doc = fitz.open()
        for _ in range(4):
            page = doc.new_page(width=400, height=500)
            page.insert_text((50, 20), "Clinical Study Protocol - Draft", fontsize=9)
            page.insert_text((50, 80), "5.2 Exclusion Criteria", fontsize=13)
            page.insert_text((50, 110), "Participants must not have condition X.", fontsize=11)
        doc.save(pdf_path)
        doc.close()

        index = parse_pdf_blocks(pdf_path, "h")
        texts = " ".join(b.text for b in index.blocks)
        assert "Clinical Study Protocol - Draft" not in texts
        assert "condition X" in texts


def test_cover_label_does_not_prefix_later_sections():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "cover.pdf"
        doc = fitz.open()
        cover = doc.new_page(width=500, height=700)
        cover.insert_text((72, 120), "AZD1222", fontsize=16)
        cover.insert_text((72, 160), "TITLE PAGE", fontsize=14)
        body = doc.new_page(width=500, height=700)
        body.insert_text((72, 120), "5.1 Inclusion Criteria", fontsize=14)
        body.insert_text((72, 160), "Adults aged 18 years or older.", fontsize=11)
        doc.save(pdf_path)
        doc.close()

        index = parse_pdf_blocks(pdf_path, "cover")
        bodies = [b for b in index.blocks if "18 years" in b.text]
        assert bodies
        assert bodies[0].section_path == "5.1 Inclusion Criteria"
        assert all(not (b.section_path or "").startswith("AZD1222") for b in index.blocks)


def test_split_heading_row_and_ignores_toc():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "split.pdf"
        doc = fitz.open()
        toc = doc.new_page(width=600, height=700)
        toc.insert_text((72, 100), "5.1", fontsize=11)
        toc.insert_text((140, 100), "Inclusion Criteria .............................. 39", fontsize=11)
        body = doc.new_page(width=600, height=700)
        body.insert_text((72, 100), "5", fontsize=14)
        body.insert_text((140, 100), "STUDY POPULATION", fontsize=14)
        body.insert_text((72, 140), "5.1", fontsize=13)
        body.insert_text((140, 140), "Inclusion Criteria", fontsize=13)
        body.insert_text((72, 180), "Participants must provide consent.", fontsize=11)
        doc.save(pdf_path)
        doc.close()

        index = parse_pdf_blocks(pdf_path, "split")
        bodies = [b for b in index.blocks if "consent" in b.text]
        assert bodies
        assert bodies[0].section_path == "5 STUDY POPULATION > 5.1 Inclusion Criteria"
        assert all("....." not in b.text for b in index.blocks)
