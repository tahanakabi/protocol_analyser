import logging
from pathlib import Path
from typing import TypeVar

from app.block_retrieval import FIELD_QUERIES, format_field_context, select_field_blocks
from app.hybrid_search import HybridIndex
from app.openai_client import client, openai_embedder
from app.pdf_outline import build_document_outline, select_outline_blocks
from app.vector_store import Embedder
from app.vector_store import registry as index_registry
from app.compose import compose_protocol_from_sections
from app.config import settings
from app.pdf_source import SOURCE_INDEX_VERSION, parse_pdf_blocks
from app.pdf_tables import extract_tables_from_pdf
from app.soa_extract import extract_schedule_of_activities
from app.schemas import (
    AssessmentsSectionLLM,
    DocumentStatus,
    Endpoints,
    EndpointsLLM,
    SafetySectionLLM,
    SectionStatus,
    SourcedCriteriaLLM,
    SourceBlock,
    SourceIndex,
    StudyObjectives,
    StudyObjectivesLLM,
    VisitsSectionLLM,
)
from app.section_storage import (
    all_sections_complete,
    init_manifest,
    read_manifest,
    section_is_done,
    set_section_status,
    write_section_payload,
)
from app.storage import (
    pdf_path,
    read_document_outline,
    read_meta,
    read_source_index,
    write_document_outline,
    write_meta,
    write_source_index,
    write_tables_raw,
)
from app.validate import (
    build_validation_summary,
    validate_assessment,
    validate_sourced_text,
    validate_visit,
)

logger = logging.getLogger(__name__)

EVIDENCE_RULES = (
    " Cite evidence: each item needs source_block_ids and evidence_quotes (same length), "
    "quotes must be exact substrings from block t. Use only ids from input."
)

CRITERIA_LIST_HINT = (
    " When the source has numbered criteria, output one item per numbered line (not only the section title)."
)


T = TypeVar("T")


def _call_structured(system: str, user: str, model_type: type[T]) -> T:
    response = client().chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=model_type,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Empty response from OpenAI")
    return parsed


def _field_query_vectors(index: HybridIndex, embed: Embedder | None) -> dict[str, list[float]]:
    if not index.has_vectors or embed is None:
        return {}
    keys = list(FIELD_QUERIES)
    try:
        vectors = embed([FIELD_QUERIES[key].description for key in keys])
    except Exception:
        logger.warning("Embedding field queries failed; using keyword retrieval only", exc_info=True)
        return {}
    return dict(zip(keys, vectors))


def _section_context(
    index: HybridIndex,
    outline,
    section_key: str,
    query_vectors: dict[str, list[float]],
) -> str:
    outline_selection = select_outline_blocks(outline, index.blocks, section_key)
    selection = select_field_blocks(
        index,
        section_key,
        query_vectors.get(section_key),
        outline_selection.blocks,
        outline_selection.labels,
        settings.llm_context_char_budget,
        settings.max_block_text_chars,
        settings.retrieval_extra_blocks,
        settings.retrieval_min_blocks,
        exclude_pages=frozenset(outline.toc_pages),
    )
    logger.info(
        "Context for %s: %s outline blocks (%s) + %s %s blocks",
        section_key,
        selection.outline_blocks,
        "; ".join(selection.outline_labels) or "no outline match",
        selection.extra_blocks,
        "hybrid" if selection.semantic else "keyword",
    )
    return format_field_context(selection, section_key, settings.max_block_text_chars)


def _block_index(source_index: SourceIndex) -> dict[str, SourceBlock]:
    return {b.id: b for b in source_index.blocks}


def _map_list(block_index: dict[str, SourceBlock], items):
    return [validate_sourced_text(item, block_index) for item in items]


def _run_section(doc_dir: Path, key: str, fn) -> None:
    manifest = read_manifest(doc_dir)
    if manifest and section_is_done(manifest, key):
        return
    set_section_status(doc_dir, key, SectionStatus.processing)
    try:
        fn()
        set_section_status(doc_dir, key, SectionStatus.completed)
    except Exception as exc:
        logger.exception("Section %s failed for %s", key, doc_dir.name)
        set_section_status(doc_dir, key, SectionStatus.failed, str(exc))
        raise


def run_extraction_job(document_id: str) -> None:
    meta = read_meta(document_id)
    if meta is None:
        return

    doc_dir = pdf_path(document_id).parent
    manifest = read_manifest(doc_dir)
    if manifest and all_sections_complete(manifest):
        return

    init_manifest(doc_dir)
    path = pdf_path(document_id)

    try:
        source_index = read_source_index(document_id)
        index_rebuilt = (
            source_index is None
            or source_index.index_version < SOURCE_INDEX_VERSION
            or source_index.pdf_handler != meta.pdf_handler
        )
        if index_rebuilt:
            logger.info("Parsing %s with PDF handler %s", document_id, meta.pdf_handler)
            source_index = parse_pdf_blocks(path, meta.sha256, meta.pdf_handler)
            write_source_index(document_id, source_index)

        blocks = source_index.blocks
        block_index = _block_index(source_index)
        max_page = max((b.page for b in blocks), default=0)

        outline = read_document_outline(document_id)
        if index_rebuilt or outline is None or outline.index_version != source_index.index_version:
            outline = build_document_outline(path, source_index)
            write_document_outline(document_id, outline)
            logger.info(
                "Wrote document outline for %s (%s top-level nodes, toc pages %s)",
                document_id,
                len(outline.nodes),
                outline.toc_pages,
            )

        try:
            embed = openai_embedder()
        except ValueError:
            embed = None
        search_index = index_registry.get(
            document_id,
            source_index,
            embed,
            settings.openai_embedding_model,
            doc_dir / "embeddings.npz",
        )
        query_vectors = _field_query_vectors(search_index, embed)

        def ctx(section_key: str) -> str:
            return _section_context(search_index, outline, section_key, query_vectors)

        def extract_study_objectives() -> None:
            raw = _call_structured(
                "Extract study objectives (primary, secondary)." + EVIDENCE_RULES,
                ctx("study_objectives"),
                StudyObjectivesLLM,
            )
            write_section_payload(
                doc_dir,
                "study_objectives",
                StudyObjectives(
                    primary=_map_list(block_index, raw.primary),
                    secondary=_map_list(block_index, raw.secondary),
                ),
            )

        _run_section(doc_dir, "study_objectives", extract_study_objectives)

        def extract_endpoints() -> None:
            raw = _call_structured(
                "Extract endpoints (primary, secondary, exploratory)." + EVIDENCE_RULES,
                ctx("endpoints"),
                EndpointsLLM,
            )
            write_section_payload(
                doc_dir,
                "endpoints",
                Endpoints(
                    primary=_map_list(block_index, raw.primary),
                    secondary=_map_list(block_index, raw.secondary),
                    exploratory=_map_list(block_index, raw.exploratory),
                ),
            )

        _run_section(doc_dir, "endpoints", extract_endpoints)

        def extract_soa() -> None:
            tables_payload = extract_tables_from_pdf(path)
            write_tables_raw(document_id, tables_payload)
            soa = extract_schedule_of_activities(path, outline, tables_payload, max_page, _call_structured)
            write_section_payload(doc_dir, "schedule_of_activities", soa)

        _run_section(doc_dir, "schedule_of_activities", extract_soa)

        def extract_inclusion() -> None:
            raw = _call_structured(
                "Extract inclusion criteria." + CRITERIA_LIST_HINT + EVIDENCE_RULES,
                ctx("inclusion_criteria"),
                SourcedCriteriaLLM,
            )
            write_section_payload(doc_dir, "inclusion_criteria", _map_list(block_index, raw.items))

        _run_section(doc_dir, "inclusion_criteria", extract_inclusion)

        def extract_exclusion() -> None:
            raw = _call_structured(
                "Extract exclusion criteria." + CRITERIA_LIST_HINT + EVIDENCE_RULES,
                ctx("exclusion_criteria"),
                SourcedCriteriaLLM,
            )
            write_section_payload(doc_dir, "exclusion_criteria", _map_list(block_index, raw.items))

        _run_section(doc_dir, "exclusion_criteria", extract_exclusion)

        def extract_visits() -> None:
            raw = _call_structured(
                "Extract visit definitions (name, timing, window, notes)." + EVIDENCE_RULES,
                ctx("visits"),
                VisitsSectionLLM,
            )
            write_section_payload(
                doc_dir,
                "visits",
                [validate_visit(v, block_index) for v in raw.visits],
            )

        _run_section(doc_dir, "visits", extract_visits)

        def extract_assessments() -> None:
            raw = _call_structured(
                "Extract key assessments and procedures." + EVIDENCE_RULES,
                ctx("key_assessments_and_procedures"),
                AssessmentsSectionLLM,
            )
            write_section_payload(
                doc_dir,
                "key_assessments_and_procedures",
                [validate_assessment(a, block_index) for a in raw.items],
            )

        _run_section(doc_dir, "key_assessments_and_procedures", extract_assessments)

        def extract_safety() -> None:
            raw = _call_structured(
                "Extract safety monitoring rules, or null if absent." + EVIDENCE_RULES,
                ctx("safety_monitoring_rules"),
                SafetySectionLLM,
            )
            payload = _map_list(block_index, raw.rules) if raw.rules else None
            write_section_payload(doc_dir, "safety_monitoring_rules", payload)

        _run_section(doc_dir, "safety_monitoring_rules", extract_safety)

        def extract_notes() -> None:
            # No LLM call — saves tokens; optional human-facing note from validation later.
            write_section_payload(doc_dir, "extraction_notes", None)

        _run_section(doc_dir, "extraction_notes", extract_notes)

        def extract_validation() -> None:
            protocol = compose_protocol_from_sections(doc_dir)
            summary = build_validation_summary(protocol)
            write_section_payload(doc_dir, "validation", summary)

        _run_section(doc_dir, "validation", extract_validation)

        meta.status = DocumentStatus.completed
        meta.error = None
        write_meta(meta)
    except Exception as exc:
        meta = read_meta(document_id)
        if meta:
            meta.status = DocumentStatus.failed
            meta.error = str(exc)
            write_meta(meta)
