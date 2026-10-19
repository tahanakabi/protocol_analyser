from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAIError

from app.config import settings
from app.extract import run_extraction_job
from app.pdf_handlers import DEFAULT_HANDLER, HANDLERS
from app.sections import EXTRACTION_SECTION_KEYS
from app.rag import answer_question
from app.schemas import (
    ChatRequest,
    ChatResponse,
    DocumentDetail,
    DocumentMeta,
    DocumentOutline,
    DocumentStatus,
    DocumentSummary,
    PdfHandlerInfo,
    SourceIndex,
)
from app.section_storage import (
    all_sections_complete,
    init_manifest,
    read_manifest,
    read_section_payload,
    section_is_done,
)
from app.storage import (
    ExtractionLock,
    create_document_record,
    list_documents,
    pdf_path,
    read_document_outline,
    read_meta,
    read_source_index,
    sha256_bytes,
    write_meta,
)

app = FastAPI(title="Protocol Analyser API", version="1.0.0")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/pdf-handlers", response_model=list[PdfHandlerInfo])
def get_pdf_handlers() -> list[PdfHandlerInfo]:
    infos = []
    for handler in HANDLERS.values():
        reason = handler.unavailable_reason()
        infos.append(
            PdfHandlerInfo(
                id=handler.id,
                label=handler.label,
                description=handler.description,
                speed=handler.speed,
                available=reason is None,
                unavailable_reason=reason,
            )
        )
    return infos


@app.get("/api/documents", response_model=list[DocumentSummary])
def get_documents() -> list[DocumentSummary]:
    return list_documents()


@app.get("/api/documents/{document_id}/pdf")
def get_document_pdf(document_id: str) -> FileResponse:
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = pdf_path(document_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{meta.original_filename}"',
        },
    )


@app.get("/api/documents/{document_id}/source-index", response_model=SourceIndex)
def get_source_index(document_id: str) -> SourceIndex:
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    index = read_source_index(document_id)
    if index is None:
        raise HTTPException(status_code=404, detail="Source index not found")
    return index


@app.get("/api/documents/{document_id}/outline", response_model=DocumentOutline)
def get_document_outline(document_id: str) -> DocumentOutline:
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    outline = read_document_outline(document_id)
    if outline is None:
        raise HTTPException(status_code=404, detail="Document outline not found")
    return outline


@app.get("/api/documents/{document_id}/sections/{section_key}")
def get_document_section(document_id: str, section_key: str):
    if section_key not in EXTRACTION_SECTION_KEYS:
        raise HTTPException(status_code=404, detail="Unknown section")
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_dir = pdf_path(document_id).parent
    manifest = read_manifest(doc_dir)
    if manifest is None or not section_is_done(manifest, section_key):
        raise HTTPException(status_code=404, detail="Section not ready")
    payload = read_section_payload(doc_dir, section_key)
    if payload is None:
        raise HTTPException(status_code=404, detail="Section file missing")
    return JSONResponse(content=payload)


@app.post("/api/documents/{document_id}/chat", response_model=ChatResponse)
def chat_with_document(document_id: str, request: ChatRequest) -> ChatResponse:
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    source_index = read_source_index(document_id)
    if source_index is None:
        raise HTTPException(status_code=409, detail="Document is still being parsed")
    try:
        return answer_question(
            document_id,
            source_index,
            request,
            cache_path=pdf_path(document_id).parent / "embeddings.npz",
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OpenAIError as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc


@app.get("/api/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str) -> DocumentDetail:
    meta = read_meta(document_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_dir = pdf_path(document_id).parent
    manifest = read_manifest(doc_dir)
    return DocumentDetail(meta=meta, sections=manifest, extraction=None)


def _queue_extraction(document_id: str, background_tasks: BackgroundTasks) -> None:
    doc_dir = pdf_path(document_id).parent
    manifest = read_manifest(doc_dir)
    if manifest and all_sections_complete(manifest):
        meta = read_meta(document_id)
        if meta and meta.status != DocumentStatus.completed:
            meta.status = DocumentStatus.completed
            meta.error = None
            write_meta(meta)
        return

    def _job() -> None:
        with ExtractionLock(document_id):
            doc_dir_inner = pdf_path(document_id).parent
            manifest_inner = read_manifest(doc_dir_inner)
            if manifest_inner and all_sections_complete(manifest_inner):
                return
            meta_inner = read_meta(document_id)
            if meta_inner:
                meta_inner.status = DocumentStatus.processing
                meta_inner.error = None
                write_meta(meta_inner)
            run_extraction_job(document_id)

    background_tasks.add_task(_job)


@app.post("/api/documents", response_model=DocumentSummary)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    pdf_handler: str = Form(DEFAULT_HANDLER),
) -> DocumentSummary:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    handler = HANDLERS.get(pdf_handler)
    if handler is None:
        raise HTTPException(status_code=400, detail=f"Unknown PDF handler: {pdf_handler}")
    reason = handler.unavailable_reason()
    if reason:
        raise HTTPException(status_code=400, detail=f"{handler.label} is not available: {reason}")

    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="File too large")

    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Invalid PDF file")

    file_hash = sha256_bytes(data)
    meta = create_document_record(file.filename, file_hash, data, pdf_handler)

    doc_dir = pdf_path(meta.id).parent
    manifest = read_manifest(doc_dir)
    if manifest is None:
        init_manifest(doc_dir)
    manifest = read_manifest(doc_dir)
    if manifest is None or not all_sections_complete(manifest):
        _queue_extraction(meta.id, background_tasks)
        meta = read_meta(meta.id) or meta

    return DocumentSummary(
        id=meta.id,
        original_filename=meta.original_filename,
        sha256=meta.sha256,
        uploaded_at=meta.uploaded_at,
        status=meta.status,
        error=meta.error,
        pdf_handler=meta.pdf_handler,
    )
