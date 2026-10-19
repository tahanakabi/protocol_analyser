import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import portalocker

from app.config import settings
from app.schemas import (
    DocumentMeta,
    DocumentStatus,
    DocumentSummary,
    ProtocolExtraction,
    DocumentOutline,
    SourceIndex,
    TablesRawPayload,
)


def _storage_root() -> Path:
    root = settings.storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path() -> Path:
    return _storage_root() / "index.json"


def _documents_dir() -> Path:
    d = _storage_root() / "documents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _doc_dir(document_id: str) -> Path:
    return _documents_dir() / document_id


def _lock_path(document_id: str) -> Path:
    return _doc_dir(document_id) / ".lock"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_index() -> dict[str, str]:
    path = _index_path()
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_index(index: dict[str, str]) -> None:
    path = _index_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2)


def _index_key(file_hash: str, pdf_handler: str) -> str:
    return f"{file_hash}:{pdf_handler}"


def find_document_id_by_hash(file_hash: str, pdf_handler: str = "pymupdf") -> str | None:
    index = _read_index()
    found = index.get(_index_key(file_hash, pdf_handler))
    if found is None and pdf_handler == "pymupdf":
        # Entries written before handlers existed are keyed by the bare hash.
        found = index.get(file_hash)
    return found


def register_hash(file_hash: str, document_id: str, pdf_handler: str = "pymupdf") -> None:
    index = _read_index()
    index[_index_key(file_hash, pdf_handler)] = document_id
    _write_index(index)


def create_document_record(
    original_filename: str,
    file_hash: str,
    pdf_bytes: bytes,
    pdf_handler: str = "pymupdf",
) -> DocumentMeta:
    """One document per (PDF, handler) pair, so the same protocol can be compared across parsers."""
    existing = find_document_id_by_hash(file_hash, pdf_handler)
    if existing:
        meta = read_meta(existing)
        if meta is not None:
            return meta

    document_id = str(uuid.uuid4())
    doc_dir = _doc_dir(document_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = doc_dir / "source.pdf"
    pdf_path.write_bytes(pdf_bytes)

    meta = DocumentMeta(
        id=document_id,
        original_filename=original_filename,
        sha256=file_hash,
        uploaded_at=datetime.now(timezone.utc),
        status=DocumentStatus.processing,
        pdf_handler=pdf_handler,
    )
    write_meta(meta)
    register_hash(file_hash, document_id, pdf_handler)
    return meta


def write_meta(meta: DocumentMeta) -> None:
    path = _doc_dir(meta.id) / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(meta.model_dump_json(indent=2))


def read_meta(document_id: str) -> DocumentMeta | None:
    path = _doc_dir(document_id) / "meta.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return DocumentMeta.model_validate_json(f.read())


def pdf_path(document_id: str) -> Path:
    return _doc_dir(document_id) / "source.pdf"


def write_extraction(document_id: str, extraction: ProtocolExtraction) -> None:
    path = _doc_dir(document_id) / "extraction.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(extraction.model_dump_json(indent=2))


def read_extraction(document_id: str) -> ProtocolExtraction | None:
    path = _doc_dir(document_id) / "extraction.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return ProtocolExtraction.model_validate_json(f.read())


def write_tables_raw(document_id: str, payload: TablesRawPayload) -> None:
    path = _doc_dir(document_id) / "tables_raw.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(payload.model_dump_json(indent=2))


def write_source_index(document_id: str, index: SourceIndex) -> None:
    path = _doc_dir(document_id) / "source_index.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(index.model_dump_json(indent=2))


def write_document_outline(document_id: str, outline: DocumentOutline) -> None:
    path = _doc_dir(document_id) / "document_outline.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(outline.model_dump_json(indent=2))


def read_document_outline(document_id: str) -> DocumentOutline | None:
    path = _doc_dir(document_id) / "document_outline.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return DocumentOutline.model_validate_json(f.read())


def read_source_index(document_id: str) -> SourceIndex | None:
    path = _doc_dir(document_id) / "source_index.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return SourceIndex.model_validate_json(f.read())


def read_tables_raw(document_id: str) -> TablesRawPayload | None:
    path = _doc_dir(document_id) / "tables_raw.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return TablesRawPayload.model_validate_json(f.read())


def list_documents() -> list[DocumentSummary]:
    docs_dir = _documents_dir()
    summaries: list[DocumentSummary] = []
    if not docs_dir.exists():
        return summaries
    for child in docs_dir.iterdir():
        if not child.is_dir():
            continue
        meta = read_meta(child.name)
        if meta is None:
            continue
        summaries.append(
            DocumentSummary(
                id=meta.id,
                original_filename=meta.original_filename,
                sha256=meta.sha256,
                uploaded_at=meta.uploaded_at,
                status=meta.status,
                error=meta.error,
                pdf_handler=meta.pdf_handler,
            )
        )
    summaries.sort(key=lambda s: s.uploaded_at, reverse=True)
    return summaries


class ExtractionLock:
    """Exclusive lock for running extraction once per document."""

    def __init__(self, document_id: str) -> None:
        self.document_id = document_id
        self._file = None

    def __enter__(self):
        doc_dir = _doc_dir(self.document_id)
        doc_dir.mkdir(parents=True, exist_ok=True)
        lock_path = _lock_path(self.document_id)
        self._file = open(lock_path, "a+")
        portalocker.lock(self._file, portalocker.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            portalocker.unlock(self._file)
            self._file.close()
            self._file = None
