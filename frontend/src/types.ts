export type DocumentStatus = "processing" | "completed" | "failed";

export type CellState = "marked" | "absent" | "text" | "na";

export type SoaConfidence = "high" | "medium" | "low";

export interface ResolvedSource {
  block_id: string;
  page: number;
  bbox: number[];
  quote: string;
  quote_matched: boolean;
}

export interface SourcedText {
  text: string;
  sources: ResolvedSource[];
  evidence_valid: boolean;
}

export interface ValidationSummary {
  total_sourced_items: number;
  valid_items: number;
  invalid_items: number;
  soa_structural_valid: boolean;
  needs_review: boolean;
}

export interface SourceBlock {
  id: string;
  page: number;
  bbox: number[];
  text: string;
  section_path?: string | null;
}

export interface SourceIndex {
  document_sha256: string;
  blocks: SourceBlock[];
}

export interface DocumentSummary {
  id: string;
  original_filename: string;
  sha256: string;
  uploaded_at: string;
  status: DocumentStatus;
  error?: string | null;
  pdf_handler: string;
}

export interface PdfHandlerInfo {
  id: string;
  label: string;
  description: string;
  speed: "fast" | "medium" | "slow";
  available: boolean;
  unavailable_reason?: string | null;
}

export interface StudyObjectives {
  primary: SourcedText[];
  secondary: SourcedText[];
}

export interface Endpoints {
  primary: SourcedText[];
  secondary: SourcedText[];
  exploratory: SourcedText[];
}

export interface SoaVisit {
  label: string;
  timing?: string | null;
  window?: string | null;
  visit_type?: string | null;
  notes: string[];
}

export interface SoaOccurrence {
  visit: string;
  detail?: string | null;
}

export interface SoaActivity {
  name: string;
  category?: string | null;
  occurrences: SoaOccurrence[];
  note?: string | null;
  footnotes: string[];
  section_reference?: string | null;
  page: number;
  found_on_page: boolean;
  bbox?: number[] | null;
  unknown_visits: string[];
}

export interface SoaFootnote {
  marker: string;
  text: string;
}

export interface SoaSchedule {
  table_label?: string | null;
  title: string;
  population?: string | null;
  pages: number[];
  visits: SoaVisit[];
  activities: SoaActivity[];
  footnotes: SoaFootnote[];
  abbreviations: string[];
}

export interface ScheduleOfActivities {
  title: string;
  schedules: SoaSchedule[];
  summary: string;
  source_pages: number[];
  notes?: string | null;
  confidence: SoaConfidence;
  structural_valid: boolean;
}

export interface VisitDefinition {
  name: SourcedText;
  timing: SourcedText;
  window?: SourcedText | null;
  notes?: SourcedText | null;
}

export interface AssessmentProcedure {
  name: SourcedText;
  description?: SourcedText | null;
  visit_or_timepoint?: SourcedText | null;
}

export interface ProtocolExtraction {
  study_objectives: StudyObjectives;
  endpoints: Endpoints;
  schedule_of_activities: ScheduleOfActivities;
  inclusion_criteria: SourcedText[];
  exclusion_criteria: SourcedText[];
  visits: VisitDefinition[];
  key_assessments_and_procedures: AssessmentProcedure[];
  safety_monitoring_rules: SourcedText[] | null;
  extraction_notes?: SourcedText | null;
  validation?: ValidationSummary | null;
}

export interface DocumentMeta {
  id: string;
  original_filename: string;
  sha256: string;
  uploaded_at: string;
  status: DocumentStatus;
  error?: string | null;
  pdf_handler: string;
}

export type SectionStatus = "pending" | "processing" | "completed" | "failed";

export interface SectionsManifest {
  sections: Record<string, SectionStatus>;
  section_errors?: Record<string, string>;
}

export interface DocumentDetail {
  meta: DocumentMeta;
  sections: SectionsManifest | null;
  extraction?: ProtocolExtraction | null;
}

export interface PdfHighlight {
  page: number;
  bbox: number[];
  label?: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatSource {
  block_id: string;
  page: number;
  bbox: number[];
  section_path?: string | null;
  text: string;
  score: number;
  keyword_rank?: number | null;
  semantic_rank?: number | null;
  cited: boolean;
}

export interface ChatResponse {
  answer: string;
  retrieval: "hybrid" | "keyword";
  sources: ChatSource[];
}
