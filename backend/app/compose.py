from pathlib import Path

from app.schemas import (
    AssessmentProcedure,
    Endpoints,
    ProtocolExtraction,
    ScheduleOfActivities,
    SourcedText,
    StudyObjectives,
    ValidationSummary,
    VisitDefinition,
    empty_schedule_of_activities,
)
from app.section_storage import read_section_payload


def compose_protocol_from_sections(doc_dir: Path) -> ProtocolExtraction:
    def load_model(key: str, model_type: type):
        raw = read_section_payload(doc_dir, key)
        if raw is None:
            return None
        return model_type.model_validate(raw)

    study = load_model("study_objectives", StudyObjectives) or StudyObjectives()
    endpoints = load_model("endpoints", Endpoints) or Endpoints()
    soa = load_model("schedule_of_activities", ScheduleOfActivities) or empty_schedule_of_activities()

    inclusion = read_section_payload(doc_dir, "inclusion_criteria")
    exclusion = read_section_payload(doc_dir, "exclusion_criteria")
    visits_raw = read_section_payload(doc_dir, "visits")
    assessments_raw = read_section_payload(doc_dir, "key_assessments_and_procedures")
    safety_raw = read_section_payload(doc_dir, "safety_monitoring_rules")
    notes_raw = read_section_payload(doc_dir, "extraction_notes")
    validation_raw = read_section_payload(doc_dir, "validation")

    return ProtocolExtraction(
        study_objectives=study,
        endpoints=endpoints,
        schedule_of_activities=soa,
        inclusion_criteria=[SourcedText.model_validate(x) for x in (inclusion or [])],
        exclusion_criteria=[SourcedText.model_validate(x) for x in (exclusion or [])],
        visits=[VisitDefinition.model_validate(x) for x in (visits_raw or [])],
        key_assessments_and_procedures=[
            AssessmentProcedure.model_validate(x) for x in (assessments_raw or [])
        ],
        safety_monitoring_rules=(
            [SourcedText.model_validate(x) for x in safety_raw] if safety_raw else None
        ),
        extraction_notes=SourcedText.model_validate(notes_raw) if notes_raw else None,
        validation=ValidationSummary.model_validate(validation_raw) if validation_raw else None,
    )
