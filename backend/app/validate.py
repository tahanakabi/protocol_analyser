import re

from app.schemas import (
    AssessmentProcedure,
    AssessmentProcedureLLM,
    Endpoints,
    ProtocolExtraction,
    ProtocolExtractionLLM,
    ResolvedSource,
    ScheduleOfActivities,
    SourcedText,
    SourcedTextLLM,
    SourceBlock,
    SourceIndex,
    StudyObjectives,
    ValidationSummary,
    VisitDefinition,
    VisitDefinitionLLM,
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def quote_matches_block(quote: str, block_text: str) -> bool:
    q = _normalize_whitespace(quote)
    if not q:
        return False
    t = _normalize_whitespace(block_text)
    if q in t:
        return True
    return q.lower() in t.lower()


def validate_sourced_text(
    raw: SourcedTextLLM,
    block_index: dict[str, SourceBlock],
) -> SourcedText:
    text = raw.text
    source_block_ids = raw.source_block_ids
    evidence_quotes = raw.evidence_quotes
    sources: list[ResolvedSource] = []
    valid = True

    if not text.strip():
        return SourcedText(text=text, sources=[], evidence_valid=True)

    if not source_block_ids or len(source_block_ids) != len(evidence_quotes):
        valid = False
    else:
        for block_id, quote in zip(source_block_ids, evidence_quotes):
            block = block_index.get(block_id)
            if block is None:
                valid = False
                sources.append(
                    ResolvedSource(
                        block_id=block_id,
                        page=0,
                        bbox=[],
                        quote=quote,
                        quote_matched=False,
                    )
                )
                continue
            matched = quote_matches_block(quote, block.text)
            if not matched:
                valid = False
            sources.append(
                ResolvedSource(
                    block_id=block_id,
                    page=block.page,
                    bbox=block.bbox,
                    quote=quote,
                    quote_matched=matched,
                )
            )

    return SourcedText(text=text, sources=sources, evidence_valid=valid)


def validate_visit(raw: VisitDefinitionLLM, block_index: dict[str, SourceBlock]) -> VisitDefinition:
    return VisitDefinition(
        name=validate_sourced_text(raw.name, block_index),
        timing=validate_sourced_text(raw.timing, block_index),
        window=validate_sourced_text(raw.window, block_index) if raw.window else None,
        notes=validate_sourced_text(raw.notes, block_index) if raw.notes else None,
    )


def validate_assessment(
    raw: AssessmentProcedureLLM,
    block_index: dict[str, SourceBlock],
) -> AssessmentProcedure:
    return AssessmentProcedure(
        name=validate_sourced_text(raw.name, block_index),
        description=validate_sourced_text(raw.description, block_index) if raw.description else None,
        visit_or_timepoint=(
            validate_sourced_text(raw.visit_or_timepoint, block_index)
            if raw.visit_or_timepoint
            else None
        ),
    )


def validate_soa_structure(soa: ScheduleOfActivities, max_page: int) -> ScheduleOfActivities:
    """Page sanity only; soa_extract.validate_schedules does the per-activity checks."""
    pages_ok = all(1 <= p <= max_page for p in soa.source_pages) if max_page else True
    soa.structural_valid = soa.structural_valid and pages_ok
    return soa


def _walk_sourced_texts(extraction: ProtocolExtraction) -> list[SourcedText]:
    out: list[SourcedText] = []
    for lst in (
        extraction.study_objectives.primary,
        extraction.study_objectives.secondary,
        extraction.endpoints.primary,
        extraction.endpoints.secondary,
        extraction.endpoints.exploratory,
        extraction.inclusion_criteria,
        extraction.exclusion_criteria,
    ):
        out.extend(lst)
    if extraction.safety_monitoring_rules:
        out.extend(extraction.safety_monitoring_rules)
    if extraction.extraction_notes:
        out.append(extraction.extraction_notes)
    for v in extraction.visits:
        out.append(v.name)
        out.append(v.timing)
        if v.window:
            out.append(v.window)
        if v.notes:
            out.append(v.notes)
    for a in extraction.key_assessments_and_procedures:
        out.append(a.name)
        if a.description:
            out.append(a.description)
        if a.visit_or_timepoint:
            out.append(a.visit_or_timepoint)
    return [s for s in out if s.text.strip()]


def build_validation_summary(extraction: ProtocolExtraction) -> ValidationSummary:
    items = _walk_sourced_texts(extraction)
    total = len(items)
    valid = sum(1 for i in items if i.evidence_valid)
    invalid = total - valid
    soa_ok = extraction.schedule_of_activities.structural_valid
    return ValidationSummary(
        total_sourced_items=total,
        valid_items=valid,
        invalid_items=invalid,
        soa_structural_valid=soa_ok,
        needs_review=invalid > 0 or not soa_ok,
    )


def llm_to_validated_extraction(
    raw: ProtocolExtractionLLM,
    source_index: SourceIndex,
) -> ProtocolExtraction:
    block_index = {b.id: b for b in source_index.blocks}
    max_page = max((b.page for b in source_index.blocks), default=0)

    def map_list(items: list[SourcedTextLLM]) -> list[SourcedText]:
        return [validate_sourced_text(item, block_index) for item in items]

    soa = validate_soa_structure(raw.schedule_of_activities, max_page)

    extraction = ProtocolExtraction(
        study_objectives=StudyObjectives(
            primary=map_list(raw.study_objectives.primary),
            secondary=map_list(raw.study_objectives.secondary),
        ),
        endpoints=Endpoints(
            primary=map_list(raw.endpoints.primary),
            secondary=map_list(raw.endpoints.secondary),
            exploratory=map_list(raw.endpoints.exploratory),
        ),
        schedule_of_activities=soa,
        inclusion_criteria=map_list(raw.inclusion_criteria),
        exclusion_criteria=map_list(raw.exclusion_criteria),
        visits=[validate_visit(v, block_index) for v in raw.visits],
        key_assessments_and_procedures=[
            validate_assessment(a, block_index) for a in raw.key_assessments_and_procedures
        ],
        safety_monitoring_rules=map_list(raw.safety_monitoring_rules) if raw.safety_monitoring_rules else None,
        extraction_notes=(
            validate_sourced_text(raw.extraction_notes, block_index) if raw.extraction_notes else None
        ),
    )
    extraction.validation = build_validation_summary(extraction)
    return extraction
