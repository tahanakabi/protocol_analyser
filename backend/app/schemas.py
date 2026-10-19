from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    processing = "processing"
    completed = "completed"
    failed = "failed"


# --- Source index (immutable PDF blocks) ---


class SourceBlock(BaseModel):
    id: str
    page: int
    bbox: list[float]
    text: str
    section_path: str | None = None


class SourceIndex(BaseModel):
    document_sha256: str
    blocks: list[SourceBlock] = Field(default_factory=list)
    index_version: int = 1
    pdf_handler: str = "pymupdf"


class OutlineNode(BaseModel):
    """One table-of-contents section and the paragraph blocks that belong to it."""

    number: str | None = None
    title: str
    page_start: int
    page_end: int
    block_ids: list[str] = Field(default_factory=list)
    children: list["OutlineNode"] = Field(default_factory=list)


class DocumentOutline(BaseModel):
    index_version: int
    toc_pages: list[int] = Field(default_factory=list)
    nodes: list[OutlineNode] = Field(default_factory=list)


class ResolvedSource(BaseModel):
    block_id: str
    page: int
    bbox: list[float]
    quote: str
    quote_matched: bool


class SourcedTextLLM(BaseModel):
    text: str
    source_block_ids: list[str]
    evidence_quotes: list[str]


class SourcedText(BaseModel):
    text: str
    sources: list[ResolvedSource] = Field(default_factory=list)
    evidence_valid: bool = False


class ValidationSummary(BaseModel):
    total_sourced_items: int
    valid_items: int
    invalid_items: int
    soa_structural_valid: bool
    needs_review: bool


# --- LLM extraction shapes ---


class StudyObjectivesLLM(BaseModel):
    primary: list[SourcedTextLLM] = Field(default_factory=list)
    secondary: list[SourcedTextLLM] = Field(default_factory=list)


class EndpointsLLM(BaseModel):
    primary: list[SourcedTextLLM] = Field(default_factory=list)
    secondary: list[SourcedTextLLM] = Field(default_factory=list)
    exploratory: list[SourcedTextLLM] = Field(default_factory=list)


class VisitDefinitionLLM(BaseModel):
    name: SourcedTextLLM
    timing: SourcedTextLLM
    window: SourcedTextLLM | None = None
    notes: SourcedTextLLM | None = None


class AssessmentProcedureLLM(BaseModel):
    name: SourcedTextLLM
    description: SourcedTextLLM | None = None
    visit_or_timepoint: SourcedTextLLM | None = None


class SourcedCriteriaLLM(BaseModel):
    items: list[SourcedTextLLM] = Field(default_factory=list)


class VisitsSectionLLM(BaseModel):
    visits: list[VisitDefinitionLLM] = Field(default_factory=list)


class AssessmentsSectionLLM(BaseModel):
    items: list[AssessmentProcedureLLM] = Field(default_factory=list)


class SafetySectionLLM(BaseModel):
    rules: list[SourcedTextLLM] | None = None


class ExtractionNotesSectionLLM(BaseModel):
    notes: SourcedTextLLM | None = None


class SectionStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class SectionsManifest(BaseModel):
    sections: dict[str, SectionStatus] = Field(default_factory=dict)
    section_errors: dict[str, str] = Field(default_factory=dict)


# --- Validated extraction (persisted) ---


class StudyObjectives(BaseModel):
    primary: list[SourcedText] = Field(default_factory=list)
    secondary: list[SourcedText] = Field(default_factory=list)


class Endpoints(BaseModel):
    primary: list[SourcedText] = Field(default_factory=list)
    secondary: list[SourcedText] = Field(default_factory=list)
    exploratory: list[SourcedText] = Field(default_factory=list)


class CellState(str, Enum):
    marked = "marked"
    absent = "absent"
    text = "text"
    na = "na"


class SoaConfidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class SoaVisitLLM(BaseModel):
    label: str = Field(description="Column header exactly as printed, e.g. 'Day 8' or 'V3'; unique within the table")
    timing: str | None = Field(None, description="Study day, week or period this visit represents")
    window: str | None = Field(None, description="Visit window as printed, e.g. '± 3' or '-3 to +7'")
    visit_type: str | None = Field(None, description="Column group such as 'Site Visit', 'Home Collection', 'Telephone'")
    notes: list[str] = Field(default_factory=list, description="Footnote texts attached to this visit header, resolved")


class SoaOccurrenceLLM(BaseModel):
    visit: str = Field(description="Label of one visit in this table's visits list")
    detail: str | None = Field(None, description="Cell qualifier other than a plain X, e.g. 'predose', 'if indicated'")


class SoaActivityLLM(BaseModel):
    name: str = Field(description="Procedure name as printed in the first column, without footnote markers")
    category: str | None = Field(None, description="Group row this activity sits under, e.g. 'Efficacy assessments'")
    occurrences: list[SoaOccurrenceLLM] = Field(default_factory=list)
    note: str | None = Field(None, description="Text that spans visit columns, e.g. 'As applicable, for treatment of SAE'")
    footnotes: list[str] = Field(default_factory=list, description="Footnote texts referenced by this row, resolved")
    section_reference: str | None = Field(None, description="'For details see Section' value")
    page: int = Field(description="Page where the activity row appears")


class SoaFootnoteLLM(BaseModel):
    marker: str
    text: str


class SoaScheduleLLM(BaseModel):
    table_label: str | None = Field(None, description="e.g. 'Table 2'")
    title: str
    population: str | None = Field(None, description="Period, cohort or population the table applies to")
    pages: list[int]
    visits: list[SoaVisitLLM] = Field(default_factory=list)
    activities: list[SoaActivityLLM] = Field(default_factory=list)
    footnotes: list[SoaFootnoteLLM] = Field(default_factory=list)
    abbreviations: list[str] = Field(default_factory=list)


class SoaExtractionLLM(BaseModel):
    schedules: list[SoaScheduleLLM] = Field(default_factory=list)


class SoaActivity(SoaActivityLLM):
    found_on_page: bool = False
    bbox: list[float] | None = None
    unknown_visits: list[str] = Field(default_factory=list)


class SoaSchedule(SoaScheduleLLM):
    activities: list[SoaActivity] = Field(default_factory=list)


class ScheduleOfActivities(BaseModel):
    title: str = "Schedule of Activities"
    schedules: list[SoaSchedule] = Field(default_factory=list)
    summary: str = ""
    source_pages: list[int] = Field(default_factory=list)
    notes: str | None = None
    confidence: SoaConfidence = SoaConfidence.low
    structural_valid: bool = False


def empty_schedule_of_activities() -> ScheduleOfActivities:
    return ScheduleOfActivities()


class ProtocolExtractionLLM(BaseModel):
    study_objectives: StudyObjectivesLLM = Field(default_factory=StudyObjectivesLLM)
    endpoints: EndpointsLLM = Field(default_factory=EndpointsLLM)
    schedule_of_activities: ScheduleOfActivities = Field(default_factory=empty_schedule_of_activities)
    inclusion_criteria: list[SourcedTextLLM] = Field(default_factory=list)
    exclusion_criteria: list[SourcedTextLLM] = Field(default_factory=list)
    visits: list[VisitDefinitionLLM] = Field(default_factory=list)
    key_assessments_and_procedures: list[AssessmentProcedureLLM] = Field(default_factory=list)
    safety_monitoring_rules: list[SourcedTextLLM] | None = None
    extraction_notes: SourcedTextLLM | None = None


class VisitDefinition(BaseModel):
    name: SourcedText
    timing: SourcedText
    window: SourcedText | None = None
    notes: SourcedText | None = None


class AssessmentProcedure(BaseModel):
    name: SourcedText
    description: SourcedText | None = None
    visit_or_timepoint: SourcedText | None = None


class ProtocolExtraction(BaseModel):
    study_objectives: StudyObjectives = Field(default_factory=StudyObjectives)
    endpoints: Endpoints = Field(default_factory=Endpoints)
    schedule_of_activities: ScheduleOfActivities = Field(default_factory=empty_schedule_of_activities)
    inclusion_criteria: list[SourcedText] = Field(default_factory=list)
    exclusion_criteria: list[SourcedText] = Field(default_factory=list)
    visits: list[VisitDefinition] = Field(default_factory=list)
    key_assessments_and_procedures: list[AssessmentProcedure] = Field(default_factory=list)
    safety_monitoring_rules: list[SourcedText] | None = None
    extraction_notes: SourcedText | None = None
    validation: ValidationSummary | None = None


class DocumentMeta(BaseModel):
    id: str
    original_filename: str
    sha256: str
    uploaded_at: datetime
    status: DocumentStatus
    error: str | None = None
    pdf_handler: str = "pymupdf"


class DocumentSummary(BaseModel):
    id: str
    original_filename: str
    sha256: str
    uploaded_at: datetime
    status: DocumentStatus
    error: str | None = None
    pdf_handler: str = "pymupdf"


class PdfHandlerInfo(BaseModel):
    id: str
    label: str
    description: str
    speed: Literal["fast", "medium", "slow"]
    available: bool
    unavailable_reason: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatAnswerLLM(BaseModel):
    answer: str
    cited_block_ids: list[str] = Field(default_factory=list)


class ChatSource(BaseModel):
    block_id: str
    page: int
    bbox: list[float]
    section_path: str | None = None
    text: str
    # Reciprocal-rank-fusion score, plus the block's rank in each list (None = not in that list's top results).
    score: float
    keyword_rank: int | None = None
    semantic_rank: int | None = None
    cited: bool = False


class ChatResponse(BaseModel):
    answer: str
    retrieval: Literal["hybrid", "keyword"] = "hybrid"
    sources: list[ChatSource]


class DocumentDetail(BaseModel):
    meta: DocumentMeta
    sections: SectionsManifest | None = None
    extraction: ProtocolExtraction | None = None


class NormalizedCell(BaseModel):
    raw: str
    state: CellState
    value: str | None = None


class RawTableGrid(BaseModel):
    page_number: int
    extractor: Literal["pymupdf", "pdfplumber"]
    rows: list[list[NormalizedCell]]
    bbox: list[float] | None = None


class TablesRawPayload(BaseModel):
    tables: list[RawTableGrid] = Field(default_factory=list)
    soa_candidate_pages: list[int] = Field(default_factory=list)
