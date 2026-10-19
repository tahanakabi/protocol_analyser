"""Registry of interchangeable PDF parsers. Each turns a PDF into the same list of SourceBlocks."""

from __future__ import annotations

import importlib
import importlib.util
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.config import settings
from app.schemas import SourceBlock

DEFAULT_HANDLER = "pymupdf"

# Model-based parsers use several GB of RAM each; run one at a time.
_MODEL_LOCK = threading.Lock()


def _configure_library_caches() -> None:
    """Keep third-party model weights and caches in backend/.models instead of the home directory.

    Must run before marker, surya, unstructured or nltk is imported: they read these at import time.
    """
    root = settings.model_cache_dir
    defaults = {
        "MODEL_CACHE_DIR": root / "datalab" / "models",
        "HF_HOME": root / "huggingface",
        # unstructured only looks for NLTK packages in directories named "nltk_data".
        "NLTK_DATA": root / "nltk_data",
        "NUMBA_CACHE_DIR": root / "numba",
        "MPLCONFIGDIR": root / "matplotlib",
    }
    for name, path in defaults.items():
        if name not in os.environ:
            Path(path).mkdir(parents=True, exist_ok=True)
            os.environ[name] = str(path)


_configure_library_caches()


@dataclass(frozen=True)
class PdfHandler:
    id: str
    label: str
    description: str
    speed: Literal["fast", "medium", "slow"]
    modules: tuple[str, ...]
    entry: str
    install_hint: str
    uses_models: bool = False

    def unavailable_reason(self) -> str | None:
        missing = [name for name in self.modules if importlib.util.find_spec(name) is None]
        if missing:
            return f"Python package not installed ({', '.join(missing)}). {self.install_hint}"
        return None

    def parse(self, pdf_path: Path) -> list[SourceBlock]:
        module_name, function_name = self.entry.split(":")
        function = getattr(importlib.import_module(module_name), function_name)
        if not self.uses_models:
            return function(pdf_path)
        with _MODEL_LOCK:
            return function(pdf_path)


_HANDLERS_HINT = "Install with: pip install -r requirements-handlers.txt"

HANDLERS: dict[str, PdfHandler] = {
    handler.id: handler
    for handler in (
        PdfHandler(
            id="pymupdf",
            label="PyMuPDF (built-in)",
            description="Text lines from PyMuPDF merged into paragraphs; numbered headings give the section path.",
            speed="fast",
            modules=("fitz",),
            entry="app.pdf_handlers.pymupdf_handler:parse",
            install_hint="pip install -r requirements.txt",
        ),
        PdfHandler(
            id="pdfplumber",
            label="pdfplumber",
            description="Text lines from pdfminer via pdfplumber, assembled with the same rules as PyMuPDF.",
            speed="fast",
            modules=("pdfplumber",),
            entry="app.pdf_handlers.pdfplumber_handler:parse",
            install_hint="pip install -r requirements.txt",
        ),
        PdfHandler(
            id="pymupdf4llm",
            label="pymupdf4llm",
            description="PyMuPDF layout model labels headers, section headings, list items and tables.",
            speed="medium",
            modules=("pymupdf4llm",),
            entry="app.pdf_handlers.pymupdf4llm_handler:parse",
            install_hint=_HANDLERS_HINT,
            uses_models=True,
        ),
        PdfHandler(
            id="unstructured",
            label="unstructured",
            description="unstructured.io partitioning on the PDF text layer (pdfminer); one block per element.",
            speed="fast",
            modules=("unstructured", "unstructured_inference"),
            entry="app.pdf_handlers.unstructured_handler:parse",
            install_hint=_HANDLERS_HINT,
        ),
        PdfHandler(
            id="marker",
            label="marker",
            description="marker-pdf layout model on the text layer (no OCR); a few minutes per protocol on CPU.",
            speed="slow",
            modules=("marker",),
            entry="app.pdf_handlers.marker_handler:parse",
            install_hint=_HANDLERS_HINT,
            uses_models=True,
        ),
    )
}


def get_handler(handler_id: str) -> PdfHandler:
    try:
        return HANDLERS[handler_id]
    except KeyError:
        raise ValueError(f"Unknown PDF handler: {handler_id}") from None
