from pathlib import Path

import fitz

from app.schemas import (
    DocumentOutline,
    NormalizedCell,
    OutlineNode,
    RawTableGrid,
    SoaConfidence,
    SoaExtractionLLM,
    SoaFootnoteLLM,
    SoaOccurrenceLLM,
    SoaSchedule,
    SoaScheduleLLM,
    SoaVisitLLM,
    TablesRawPayload,
    CellState,
)
from app.soa_extract import (
    SoaPage,
    clean_schedule,
    extract_schedule_of_activities,
    group_pages,
    merge_continuations,
    soa_summary,
)


def _schedule(**overrides) -> SoaSchedule:
    data = {
        "table_label": "Table 2",
        "title": "Schedule of Activities: Treatment Period",
        "pages": [2],
        "visits": [
            {"label": "Day 1", "window": "NA"},
            {"label": "Day 8 a", "window": "± 3", "notes": ["a Telephone contact only."]},
        ],
        "activities": [
            {"name": "Efficacy assessments", "page": 2},
            {
                "name": "Serum sample b",
                "category": "Efficacy assessments",
                "page": 2,
                "occurrences": [{"visit": "Day 1", "detail": "predose"}, {"visit": "8"}],
                "footnotes": ["b Collected before dosing."],
                "section_reference": "8.5.2",
            },
        ],
        "footnotes": [
            {"marker": "a", "text": "a Telephone contact only."},
            {"marker": "b", "text": "Collected before dosing."},
        ],
    }
    data.update(overrides)
    return SoaSchedule.model_validate(data)


def test_clean_schedule_strips_markers_drops_category_rows_and_resolves_visits():
    schedule = _schedule()

    clean_schedule(schedule)

    assert [v.label for v in schedule.visits] == ["Day 1", "Day 8"]
    assert schedule.visits[1].notes == ["Telephone contact only."]
    assert [a.name for a in schedule.activities] == ["Serum sample"]
    activity = schedule.activities[0]
    assert [o.visit for o in activity.occurrences] == ["Day 1", "Day 8"]
    assert activity.footnotes == ["Collected before dosing."]
    assert schedule.footnotes[0].text == "Telephone contact only."


def test_merge_continuations_joins_same_table_label():
    first = _schedule(pages=[2])
    second = _schedule(table_label="Table 2 (continued)", title="", pages=[3], activities=[{"name": "AEs", "page": 3}])

    merged = merge_continuations([first, second])

    assert len(merged) == 1
    assert merged[0].pages == [2, 3]
    assert [a.name for a in merged[0].activities][-1] == "AEs"
    assert len(merged[0].visits) == 2


def test_summary_lists_every_visit_activity_and_footnote():
    schedule = _schedule()
    clean_schedule(schedule)

    summary = soa_summary([schedule])

    assert "Table 2 – Schedule of Activities: Treatment Period" in summary
    assert "- Day 8 (window ± 3) — Telephone contact only." in summary
    assert "Efficacy assessments:\n- Serum sample: Day 1 (predose), Day 8 [Section 8.5.2]" in summary
    assert "  Note: Collected before dosing." in summary
    assert "- b: Collected before dosing." in summary


def test_repeated_caption_continues_the_table():
    pages = [
        SoaPage(1, "Table 1\nSchedule of Activities: Screening"),
        SoaPage(2, "Table 2\nSchedule of Activities: Treatment"),
        SoaPage(3, "Table 2\nSchedule of Activities: Treatment\na Footnote"),
        SoaPage(4, "a another footnote page"),
        SoaPage(5, "Table 3\nSchedule of Activities: Illness Visits"),
    ]

    assert [[p.page for p in group] for group in group_pages(pages)] == [[1], [2, 3, 4], [5]]


def _soa_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=792, height=612)
    page.insert_text((72, 80), "Table 1", fontsize=10)
    page.insert_text((72, 94), "Schedule of Activities: Screening Period", fontsize=10)
    page.insert_text((72, 130), "Medical history", fontsize=9)
    page.insert_text((300, 130), "X", fontsize=9)
    page.insert_text((72, 400), "a If screening and dosing occur at the same visit, one evaluation is required.", fontsize=8)
    doc.new_page(width=792, height=612).insert_text((72, 80), "2 INTRODUCTION", fontsize=12)
    doc.save(path)
    doc.close()
    return path


def test_extract_uses_outline_pages_and_marks_result_valid(tmp_path):
    pdf = _soa_pdf(tmp_path / "soa.pdf")
    grid = RawTableGrid(
        page_number=1,
        extractor="pymupdf",
        bbox=[70, 120, 400, 140],
        rows=[
            [
                NormalizedCell(raw="Medical history", state=CellState.text, value="Medical history"),
                NormalizedCell(raw="X", state=CellState.marked),
            ]
        ],
    )
    tables = TablesRawPayload(tables=[grid], soa_candidate_pages=[1, 2])
    outline = DocumentOutline(
        index_version=3,
        nodes=[OutlineNode(number="1.3", title="Schedule of Activities", page_start=1, page_end=1)],
    )
    prompts = []

    def fake_llm(system, user, model_type):
        prompts.append(user)
        return SoaExtractionLLM(
            schedules=[
                SoaScheduleLLM(
                    table_label="Table 1",
                    title="Schedule of Activities: Screening Period",
                    pages=[1],
                    visits=[SoaVisitLLM(label="Day -14 to Day 1")],
                    activities=[
                        {"name": "Medical history", "page": 1, "occurrences": [SoaOccurrenceLLM(visit="Day -14 to Day 1")]}
                    ],
                    footnotes=[SoaFootnoteLLM(marker="a", text="If screening and dosing occur at the same visit.")],
                )
            ]
        )

    soa = extract_schedule_of_activities(pdf, outline, tables, 2, fake_llm)

    assert len(prompts) == 1
    assert "| Medical history | X |" in prompts[0]
    assert "a If screening and dosing" in prompts[0]
    assert soa.source_pages == [1]
    assert soa.structural_valid and soa.confidence == SoaConfidence.high
    activity = soa.schedules[0].activities[0]
    assert activity.found_on_page and activity.bbox
    assert "- Medical history: Day -14 to Day 1" in soa.summary
