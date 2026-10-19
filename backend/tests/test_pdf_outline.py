import tempfile
from pathlib import Path

import fitz

from app.pdf_outline import build_document_outline, select_outline_blocks
from app.pdf_source import parse_pdf_blocks


def _write_protocol(path: Path) -> None:
    doc = fitz.open()
    toc = doc.new_page(width=600, height=800)
    toc.insert_text((72, 80), "TABLE OF CONTENTS", fontsize=14)
    toc.insert_text((72, 130), "5", fontsize=11)
    toc.insert_text((140, 130), "STUDY POPULATION .......... 2", fontsize=11)
    toc.insert_text((72, 150), "5.1", fontsize=11)
    toc.insert_text((140, 150), "Inclusion Criteria .......... 2", fontsize=11)
    toc.insert_text((72, 170), "5.2", fontsize=11)
    toc.insert_text((140, 170), "Exclusion Criteria .......... 3", fontsize=11)
    toc.insert_text((72, 190), "7", fontsize=11)
    toc.insert_text((140, 190), "DISCONTINUATION OF STUDY INTERVENTION AND PARTICIPANT", fontsize=11)
    toc.insert_text((72, 206), "DISCONTINUATION/WITHDRAWAL .......... 3", fontsize=11)

    body = doc.new_page(width=600, height=800)
    body.insert_text((72, 100), "5", fontsize=14)
    body.insert_text((140, 100), "STUDY POPULATION", fontsize=14)
    body.insert_text((72, 140), "Participants are recruited from clinics.", fontsize=11)
    body.insert_text((72, 180), "5.1", fontsize=13)
    body.insert_text((140, 180), "Inclusion Criteria", fontsize=13)
    body.insert_text((72, 220), "Must be an adult at consent.", fontsize=11)

    exclusion = doc.new_page(width=600, height=800)
    exclusion.insert_text((72, 100), "5.2", fontsize=13)
    exclusion.insert_text((140, 100), "Exclusion Criteria", fontsize=13)
    exclusion.insert_text((72, 140), "Must not be pregnant.", fontsize=11)
    doc.save(path)
    doc.close()


def test_outline_nests_toc_and_assigns_blocks():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "protocol.pdf"
        _write_protocol(pdf_path)
        source_index = parse_pdf_blocks(pdf_path, "hash")
        outline = build_document_outline(pdf_path, source_index)

        assert outline.toc_pages == [1]
        section = next(node for node in outline.nodes if node.number == "5")
        assert section.number == "5"
        assert section.title == "STUDY POPULATION"
        assert [child.number for child in section.children] == ["5.1", "5.2"]
        wrapped = next(node for node in outline.nodes if node.number == "7")
        assert wrapped.title.startswith("DISCONTINUATION OF STUDY INTERVENTION")
        assert "DISCONTINUATION/WITHDRAWAL" in wrapped.title

        inclusion = section.children[0]
        inclusion_text = " ".join(
            block.text for block in source_index.blocks if block.id in inclusion.block_ids
        )
        assert "adult" in inclusion_text.lower()
        assert "pregnant" not in inclusion_text.lower()

        selected = select_outline_blocks(outline, source_index.blocks, "inclusion_criteria")
        assert selected.labels == ["5.1 Inclusion Criteria"]
        assert any("adult" in block.text.lower() for block in selected.blocks)
        assert all("pregnant" not in block.text.lower() for block in selected.blocks)


def test_outline_selection_empty_without_toc():
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / "note.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "A short note without a contents list.", fontsize=11)
        doc.save(pdf_path)
        doc.close()
        source_index = parse_pdf_blocks(pdf_path, "hash")
        outline = build_document_outline(pdf_path, source_index)
        assert outline.nodes == []
        selected = select_outline_blocks(outline, source_index.blocks, "inclusion_criteria")
        assert selected.blocks == []
