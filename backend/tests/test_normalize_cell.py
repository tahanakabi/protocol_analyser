from app.pdf_tables import normalize_cell
from app.schemas import CellState


def test_blank_is_absent():
    assert normalize_cell("").state == CellState.absent
    assert normalize_cell("   ").state == CellState.absent


def test_x_is_marked():
    assert normalize_cell("X").state == CellState.marked
    assert normalize_cell("x").state == CellState.marked


def test_text_preserved():
    nc = normalize_cell("PK sampling")
    assert nc.state == CellState.text
    assert nc.value == "PK sampling"
