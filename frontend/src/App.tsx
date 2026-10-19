import { useCallback, useEffect, useState } from "react";
import {
  listDocuments,
  listPdfHandlers,
  pdfUrl,
  uploadDocument,
} from "./api";
import { ChatPanel } from "./components/ChatPanel";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { PdfViewer } from "./components/PdfViewer";
import { SectionShell } from "./components/SectionShell";
import { SoaView } from "./components/SoaView";
import { SourcedNotes, SourcedTextList } from "./components/SourcedTextList";
import { ValidationBanner } from "./components/ValidationBanner";
import { useDocumentSections } from "./hooks/useDocumentSections";
import type {
  DocumentSummary,
  PdfHandlerInfo,
  PdfHighlight,
  SourcedText,
} from "./types";
import "./App.css";

function ExtractionView({ documentId }: { documentId: string }) {
  const { manifest, data, sectionState } = useDocumentSections(documentId);
  const [highlights, setHighlights] = useState<PdfHighlight[]>([]);
  const [pdfPage, setPdfPage] = useState(1);
  const [tab, setTab] = useState<"fields" | "chat">("fields");

  const onInspect = useCallback((h: PdfHighlight[], page: number) => {
    setHighlights(h);
    setPdfPage(page);
  }, []);

  const sourcedField = (item: SourcedText) => (
    <SourcedTextList items={[item]} empty="" onInspect={onInspect} />
  );

  const sectionError = (key: string) => manifest?.section_errors?.[key];

  const obj = data.study_objectives;
  const ep = data.endpoints;

  return (
    <div className="verify-layout">
      <div className="extraction">
        <div className="soa-tabs view-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "fields"}
            className={tab === "fields" ? "active" : ""}
            onClick={() => setTab("fields")}
          >
            Extracted fields
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "chat"}
            className={tab === "chat" ? "active" : ""}
            onClick={() => setTab("chat")}
          >
            Ask the protocol
          </button>
        </div>

        <div hidden={tab !== "chat"}>
          <ChatPanel documentId={documentId} onInspect={onInspect} />
        </div>

        <div hidden={tab !== "fields"}>
          {data.validation && <ValidationBanner validation={data.validation} />}

          <SectionShell
            title="Notes"
            status={sectionState("extraction_notes")}
            error={sectionError("extraction_notes")}
          >
            {data.extraction_notes && (
              <SourcedNotes item={data.extraction_notes} onInspect={onInspect} />
            )}
          </SectionShell>

          <SectionShell
            title="Study objectives"
            status={sectionState("study_objectives")}
            error={sectionError("study_objectives")}
          >
            {obj && (
              <>
                <h3>Primary</h3>
                <SourcedTextList
                  items={obj.primary}
                  empty="None listed."
                  onInspect={onInspect}
                />
                <h3>Secondary</h3>
                <SourcedTextList
                  items={obj.secondary}
                  empty="None listed."
                  onInspect={onInspect}
                />
              </>
            )}
          </SectionShell>

          <SectionShell
            title="Endpoints"
            status={sectionState("endpoints")}
            error={sectionError("endpoints")}
          >
            {ep && (
              <>
                <h3>Primary</h3>
                <SourcedTextList
                  items={ep.primary}
                  empty="None listed."
                  onInspect={onInspect}
                />
                <h3>Secondary</h3>
                <SourcedTextList
                  items={ep.secondary}
                  empty="None listed."
                  onInspect={onInspect}
                />
                <h3>Exploratory</h3>
                <SourcedTextList
                  items={ep.exploratory}
                  empty="None listed."
                  onInspect={onInspect}
                />
              </>
            )}
          </SectionShell>

          <SectionShell
            title="Schedule of activities"
            status={sectionState("schedule_of_activities")}
            error={sectionError("schedule_of_activities")}
          >
            {data.schedule_of_activities && (
              <SoaView soa={data.schedule_of_activities} onInspect={onInspect} />
            )}
          </SectionShell>

          <SectionShell
            title="Inclusion criteria"
            status={sectionState("inclusion_criteria")}
            error={sectionError("inclusion_criteria")}
          >
            <SourcedTextList
              items={data.inclusion_criteria ?? []}
              empty="None listed."
              onInspect={onInspect}
            />
          </SectionShell>

          <SectionShell
            title="Exclusion criteria"
            status={sectionState("exclusion_criteria")}
            error={sectionError("exclusion_criteria")}
          >
            <SourcedTextList
              items={data.exclusion_criteria ?? []}
              empty="None listed."
              onInspect={onInspect}
            />
          </SectionShell>

          <SectionShell
            title="Visit definitions"
            status={sectionState("visits")}
            error={sectionError("visits")}
          >
            {data.visits && data.visits.length > 0 ? (
              <div className="cards">
                {data.visits.map((v, i) => (
                  <div className="card" key={i}>
                    {sourcedField(v.name)}
                    {sourcedField(v.timing)}
                    {v.window && sourcedField(v.window)}
                    {v.notes && sourcedField(v.notes)}
                  </div>
                ))}
              </div>
            ) : sectionState("visits") === "completed" ? (
              <p className="muted">None listed.</p>
            ) : null}
          </SectionShell>

          <SectionShell
            title="Key assessments and procedures"
            status={sectionState("key_assessments_and_procedures")}
            error={sectionError("key_assessments_and_procedures")}
          >
            {data.key_assessments_and_procedures &&
            data.key_assessments_and_procedures.length > 0 ? (
              <div className="cards">
                {data.key_assessments_and_procedures.map((a, i) => (
                  <div className="card" key={i}>
                    {sourcedField(a.name)}
                    {a.description && sourcedField(a.description)}
                    {a.visit_or_timepoint && sourcedField(a.visit_or_timepoint)}
                  </div>
                ))}
              </div>
            ) : sectionState("key_assessments_and_procedures") === "completed" ? (
              <p className="muted">None listed.</p>
            ) : null}
          </SectionShell>

          <SectionShell
            title="Safety monitoring rules"
            status={sectionState("safety_monitoring_rules")}
            error={sectionError("safety_monitoring_rules")}
          >
            {data.safety_monitoring_rules &&
            data.safety_monitoring_rules.length > 0 ? (
              <SourcedTextList
                items={data.safety_monitoring_rules}
                empty="None listed."
                onInspect={onInspect}
              />
            ) : sectionState("safety_monitoring_rules") === "completed" ? (
              <p className="muted">Not present in protocol.</p>
            ) : null}
          </SectionShell>
        </div>
      </div>

      <aside className="pdf-panel">
        <h2 className="sidebar-title">Source PDF</h2>
        <PdfViewer
          url={pdfUrl(documentId)}
          highlights={highlights}
          activePage={pdfPage}
        />
      </aside>
    </div>
  );
}

const HANDLER_STORAGE_KEY = "pdfHandler";
const DEFAULT_HANDLER = "pymupdf";

function App() {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [handlers, setHandlers] = useState<PdfHandlerInfo[]>([]);
  const [pdfHandler, setPdfHandler] = useState(
    () => localStorage.getItem(HANDLER_STORAGE_KEY) ?? DEFAULT_HANDLER,
  );

  useEffect(() => {
    listPdfHandlers()
      .then((list) => {
        setHandlers(list);
        setPdfHandler((current) =>
          list.some((h) => h.id === current && h.available)
            ? current
            : DEFAULT_HANDLER,
        );
      })
      .catch(() => setHandlers([]));
  }, []);

  const chooseHandler = (id: string) => {
    setPdfHandler(id);
    localStorage.setItem(HANDLER_STORAGE_KEY, id);
  };

  const handlerLabel = (id: string) =>
    handlers.find((h) => h.id === id)?.label ?? id;
  const selectedHandler = handlers.find((h) => h.id === pdfHandler);

  const refreshList = useCallback(async () => {
    try {
      const list = await listDocuments();
      setDocuments(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load documents");
    }
  }, []);

  useEffect(() => {
    refreshList();
    const id = window.setInterval(refreshList, 4000);
    return () => window.clearInterval(id);
  }, [refreshList]);

  const handleFile = async (file: File) => {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are supported.");
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const summary = await uploadDocument(file, pdfHandler);
      await refreshList();
      setSelectedId(summary.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  const selectedDoc = documents.find((d) => d.id === selectedId);

  return (
    <div className="app app-wide">
      <header>
        <h1>Clinical Protocol Analyser</h1>
        <p className="subtitle">
          Sections load incrementally as each extraction finishes
        </p>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="handler-picker">
            <label htmlFor="pdf-handler">PDF parser</label>
            <select
              id="pdf-handler"
              value={pdfHandler}
              disabled={uploading || handlers.length === 0}
              onChange={(e) => chooseHandler(e.target.value)}
            >
              {handlers.length === 0 && (
                <option value={DEFAULT_HANDLER}>PyMuPDF (built-in)</option>
              )}
              {handlers.map((h) => (
                <option
                  key={h.id}
                  value={h.id}
                  disabled={!h.available}
                  title={h.unavailable_reason ?? h.description}
                >
                  {h.label} · {h.speed}
                  {h.available ? "" : " (not installed)"}
                </option>
              ))}
            </select>
            {selectedHandler && (
              <p className="handler-description">
                {selectedHandler.description}
              </p>
            )}
          </div>

          <div
            className={`upload-zone ${dragOver ? "drag-over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <p>{uploading ? "Uploading…" : "Drop PDF here"}</p>
            <label className="file-btn">
              Choose file
              <input
                type="file"
                accept=".pdf,application/pdf"
                hidden
                disabled={uploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) handleFile(f);
                  e.target.value = "";
                }}
              />
            </label>
          </div>

          <h2 className="sidebar-title">Documents</h2>
          <ul className="doc-list">
            {documents.length === 0 && (
              <li className="muted">No documents yet</li>
            )}
            {documents.map((d) => (
              <li key={d.id}>
                <button
                  type="button"
                  className={selectedId === d.id ? "active" : ""}
                  onClick={() => setSelectedId(d.id)}
                >
                  <span className="doc-name">{d.original_filename}</span>
                  <span className="handler-badge">
                    {handlerLabel(d.pdf_handler)}
                  </span>
                  <span className={`status status-${d.status}`}>{d.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="main main-wide">
          {error && <div className="error-banner">{error}</div>}
          {!selectedId && (
            <p className="placeholder">Select or upload a protocol PDF.</p>
          )}
          {selectedId && selectedDoc?.status === "failed" && (
            <div className="error-banner">{selectedDoc.error}</div>
          )}
          {selectedId && (
            <>
              <div className="doc-header">
                <h2>{selectedDoc?.original_filename ?? "Document"}</h2>
                {selectedDoc && (
                  <span className="handler-badge">
                    Parsed with {handlerLabel(selectedDoc.pdf_handler)}
                  </span>
                )}
                {selectedDoc && (
                  <span className={`status status-${selectedDoc.status}`}>
                    {selectedDoc.status}
                  </span>
                )}
              </div>
              <ErrorBoundary>
                <ExtractionView key={selectedId} documentId={selectedId} />
              </ErrorBoundary>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export default App;
