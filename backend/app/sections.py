from app.schemas import SectionStatus

EXTRACTION_SECTION_KEYS: tuple[str, ...] = (
    "study_objectives",
    "endpoints",
    "schedule_of_activities",
    "inclusion_criteria",
    "exclusion_criteria",
    "visits",
    "key_assessments_and_procedures",
    "safety_monitoring_rules",
    "extraction_notes",
    "validation",
)


def initial_section_states() -> dict[str, SectionStatus]:
    return {key: SectionStatus.pending for key in EXTRACTION_SECTION_KEYS}
