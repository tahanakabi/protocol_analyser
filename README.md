# Clinical Protocol Analyser

Upload clinical study protocol PDFs and extract structured information with OpenAI: objectives, endpoints, Schedule of Activities (including sparse X-grid tables), eligibility criteria, visits, assessments, and safety monitoring rules.

Extractions are stored on disk and run **once per file** (deduplicated by SHA-256).

Each extraction is **source-grounded**: the LLM cites PyMuPDF text block IDs and short quotes; the backend validates that citations exist and match block text, then the UI lets you jump to the PDF page and highlight the bounding box.

## Prerequisites

- Python 3.11+
- Node.js 20+
- OpenAI API key

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env          # set OPENAI_API_KEY
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### Storage

Per document under `backend/storage/documents/{id}/`:

- `source.pdf` — uploaded file
- `meta.json` — status and metadata
- `tables_raw.json` — extracted PDF tables (normalized cells)
- `source_index.json` — immutable text blocks (`id`, `page`, `bbox`, `text`)
- `sections/manifest.json` — per-section status (`pending` → `processing` → `completed`)
- `sections/*.json` — one file per extracted field group (e.g. `study_objectives.json`, `endpoints.json`, …)

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend.

Optional: `VITE_API_BASE_URL=http://localhost:8000` if not using the proxy.

## Tests

```bash
cd backend
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -q
```

## Token / context efficiency

Each section uses **retrieval**, not the full PDF: blocks are scored by section keywords, truncated (`MAX_BLOCK_TEXT_CHARS`), and packed into `LLM_CONTEXT_CHAR_BUDGET` per API call. Prompts use compact JSON (`id`, `p`, `t`). SoA uses trimmed table grids, not full document text. Schedule of Activities does not use block retrieval.

For small-context models (e.g. 8k–16k), set in `backend/.env`:

```bash
OPENAI_MODEL=gpt-4o-mini
LLM_CONTEXT_CHAR_BUDGET=12000
MAX_BLOCK_TEXT_CHARS=800
```

## Evidence validation

1. **Parse** — `pdf_source.py` builds a block index (`p{page}_b{n}`) with coordinates.
2. **Extract** — the LLM returns `source_block_ids` + `evidence_quotes` for each field.
3. **Validate** — `validate.py` checks IDs exist and quotes appear in block text (structural verification).
4. **Review** — the UI shows `verified` / `review` badges; click a quote to open the PDF viewer with highlights.

Re-upload after code changes to regenerate extractions (same file hash reuses cache unless you remove `extraction.json`).

## Table / SoA handling

SoA tables are extracted with PyMuPDF `find_tables()` and pdfplumber as fallback. Cells are normalized (`X` / checkmarks → `marked`, blank → `absent`) before a dedicated OpenAI pass merges grids into a sparse column/row structure. If grid extraction fails, a text-only fallback runs with **low** confidence flagged in the UI.

## Security (v1)

Local development only: no authentication. Do not expose this service on the public internet without adding auth and rate limits.

## Manual smoke test

1. Start backend and frontend with a valid `OPENAI_API_KEY`.
2. Upload a text-based protocol PDF; wait until status is `completed`.
3. Confirm all sections render, especially the SoA table.
4. Re-upload the same file; it should return immediately with the same document id.
5. Restart the backend; documents and extractions should still load from disk.
