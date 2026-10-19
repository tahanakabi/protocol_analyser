from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.pdf_handlers import DEFAULT_HANDLER, HANDLERS, get_handler
from app.pdf_handlers.common import (
    RawElement,
    assemble_blocks,
    group_cell_runs,
    html_to_text,
    markdown_to_text,
)
from app.pdf_outline import select_outline_blocks
from app.pdf_source import parse_pdf_blocks
from app.schemas import DocumentOutline, OutlineNode, SourceBlock

SIZES = {1: (612.0, 792.0), 2: (612.0, 792.0)}


def _protocol_pdf(path: Path) -> Path:
    doc = fitz.open()
    for page_number in (1, 2):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 40), "Protocol XY-123 Version 2.0", fontsize=9)
        page.insert_text((300, 770), f"Page {page_number} of 2", fontsize=9)
        if page_number == 1:
            page.insert_text((72, 120), "5 STUDY POPULATION", fontsize=14)
            page.insert_text((72, 160), "5.1 Inclusion Criteria", fontsize=12)
            page.insert_text((72, 190), "Participants are eligible to be included in the study only if", fontsize=11)
            page.insert_text((72, 204), "all of the following criteria apply at screening:", fontsize=11)
        else:
            page.insert_text((72, 120), "5.2 Exclusion Criteria", fontsize=12)
            page.insert_text((72, 150), "Participants are excluded from the study if they have a history", fontsize=11)
            page.insert_text((72, 164), "of severe allergic reactions to any vaccine component.", fontsize=11)
    doc.save(path)
    doc.close()
    return path


def test_registry_lists_default_and_rejects_unknown():
    assert DEFAULT_HANDLER in HANDLERS
    assert HANDLERS[DEFAULT_HANDLER].unavailable_reason() is None
    assert {"pdfplumber", "pymupdf4llm", "unstructured", "marker"} <= set(HANDLERS)
    with pytest.raises(ValueError):
        get_handler("nope")


def test_markdown_and_html_become_quotable_text():
    assert markdown_to_text("## **5.1** Inclusion Criteria\n- Adult *aged* 18") == (
        "5.1 Inclusion Criteria\nAdult aged 18"
    )
    html = "<table><tr><th>Visit</th><th>Day</th></tr><tr><td>V1</td><td>1</td></tr></table>"
    assert html_to_text(html) == "Visit | Day\nV1 | 1"


def test_assemble_drops_margins_and_toc_and_tracks_numbered_headings():
    elements = []
    for page in (1, 2):
        elements.append(RawElement(page, (72, 30, 300, 42), "Protocol XY-123 Version 2.0", "text"))
        elements.append(RawElement(page, (300, 760, 360, 772), f"Page {page} of 2", "margin"))
    elements[2:2] = [
        RawElement(1, (72, 100, 400, 112), "1 Introduction ........ 5", "text"),
        RawElement(1, (72, 150, 90, 162), "5.1", "text"),
        RawElement(1, (100, 150, 300, 162), "Inclusion Criteria", "text"),
        RawElement(1, (72, 190, 540, 230), "Participants are eligible if all criteria apply.", "text"),
    ]
    elements.append(RawElement(2, (72, 120, 540, 200), "Visit | Day\nV1 | 1", "table"))

    blocks = assemble_blocks(elements, SIZES)

    assert [b.text for b in blocks] == ["Participants are eligible if all criteria apply.", "Visit | Day\nV1 | 1"]
    assert all(b.section_path == "5.1 Inclusion Criteria" for b in blocks)
    assert [b.id for b in blocks] == ["p1_b0", "p2_b0"]


def test_assemble_rejoins_sentence_split_at_line_break():
    elements = [
        RawElement(1, (72, 200, 540, 212), "5 Contraceptive use should be consistent with the", "text"),
        RawElement(1, (72, 213, 400, 225), "methods of contraception for participants.", "text"),
        RawElement(1, (72, 226, 300, 238), "6 Female participants", "text"),
    ]

    blocks = assemble_blocks(elements, SIZES)

    assert [b.text for b in blocks] == [
        "5 Contraceptive use should be consistent with the\nmethods of contraception for participants.",
        "6 Female participants",
    ]
    assert blocks[0].bbox == [72.0, 200.0, 540.0, 225.0]


def test_cell_runs_become_one_table_but_lists_and_numbered_items_do_not():
    cells = [
        RawElement(1, (72, 100, 200, 110), "Procedure", "text"),
        RawElement(1, (300, 100, 330, 110), "Day 1", "text"),
        RawElement(1, (72, 115, 200, 125), "Medical history", "text"),
        RawElement(1, (300, 115, 310, 125), "X", "text"),
        RawElement(1, (72, 130, 200, 140), "Vital signs", "text"),
        RawElement(1, (300, 130, 310, 140), "X", "text"),
    ]
    numbered = [
        RawElement(1, (72, 300, 80, 310), "1", "text"),
        RawElement(1, (90, 300, 400, 310), "Adult, at least 18 years of age", "text"),
        RawElement(1, (72, 315, 80, 325), "2", "text"),
        RawElement(1, (90, 315, 400, 325), "Able to give informed consent", "text"),
    ]
    single_column = [RawElement(1, (72, 400 + 15 * i, 200, 410 + 15 * i), f"Item {i}", "text") for i in range(5)]

    grouped = group_cell_runs(cells + numbered + single_column, SIZES)

    assert grouped[0].kind == "table"
    assert grouped[0].text == "Procedure | Day 1\nMedical history | X\nVital signs | X"
    assert [e.text for e in grouped[1:3]] == ["1 Adult, at least 18 years of age", "2 Able to give informed consent"]
    assert [e.kind for e in grouped[1:]] == ["text"] * 7


def test_outline_selection_keeps_reading_order_past_ten_blocks():
    blocks = [
        SourceBlock(id=f"p1_b{i}", page=1, bbox=[0, i, 1, i + 1], text=f"c{i}", section_path="5.1 Inclusion Criteria")
        for i in range(12)
    ]
    node = OutlineNode(number="5.1", title="Inclusion Criteria", page_start=1, page_end=1, block_ids=[b.id for b in blocks])
    outline = DocumentOutline(index_version=3, toc_pages=[2], nodes=[node])

    selection = select_outline_blocks(outline, blocks, "inclusion_criteria")

    assert [b.id for b in selection.blocks] == [b.id for b in blocks]


@pytest.mark.parametrize("handler_id", ["pymupdf", "pdfplumber", "pymupdf4llm", "unstructured"])
def test_fast_handlers_produce_sectioned_blocks(tmp_path, handler_id):
    reason = HANDLERS[handler_id].unavailable_reason()
    if reason:
        pytest.skip(reason)
    pdf = _protocol_pdf(tmp_path / "protocol.pdf")

    index = parse_pdf_blocks(pdf, "hash", handler_id)

    assert index.pdf_handler == handler_id
    texts = " ".join(b.text for b in index.blocks)
    assert "Protocol XY-123" not in texts and "Page 1 of 2" not in texts
    inclusion = [b for b in index.blocks if "eligible" in b.text]
    exclusion = [b for b in index.blocks if "allergic" in b.text]
    assert inclusion and exclusion
    assert inclusion[0].section_path == "5 STUDY POPULATION > 5.1 Inclusion Criteria"
    assert exclusion[0].section_path == "5 STUDY POPULATION > 5.2 Exclusion Criteria"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "storage")
    monkeypatch.setattr("app.main.run_extraction_job", lambda document_id: None)
    from app.main import app

    return TestClient(app)


def test_handler_endpoint_reports_availability(client):
    response = client.get("/api/pdf-handlers")
    assert response.status_code == 200
    by_id = {h["id"]: h for h in response.json()}
    assert by_id["pymupdf"]["available"] is True
    assert set(by_id) == set(HANDLERS)


def test_upload_keeps_one_document_per_handler(client, tmp_path):
    pdf_bytes = _protocol_pdf(tmp_path / "p.pdf").read_bytes()

    def upload(**form):
        return client.post("/api/documents", files={"file": ("p.pdf", pdf_bytes, "application/pdf")}, data=form)

    default = upload().json()
    again = upload(pdf_handler="pymupdf").json()
    plumber = upload(pdf_handler="pdfplumber").json()

    assert default["pdf_handler"] == "pymupdf"
    assert again["id"] == default["id"]
    assert plumber["id"] != default["id"] and plumber["pdf_handler"] == "pdfplumber"
    assert {d["pdf_handler"] for d in client.get("/api/documents").json()} == {"pymupdf", "pdfplumber"}
    assert upload(pdf_handler="nope").status_code == 400
