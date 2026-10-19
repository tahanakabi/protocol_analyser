import type {
  ChatMessage,
  ChatResponse,
  DocumentDetail,
  DocumentSummary,
  PdfHandlerInfo,
  SourceIndex,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || res.statusText);
  }
  return res.json() as Promise<T>;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${API_BASE}/api/documents`);
  return handleResponse(res);
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/api/documents/${id}`);
  return handleResponse(res);
}

export async function getSection(
  documentId: string,
  sectionKey: string,
): Promise<unknown> {
  const res = await fetch(
    `${API_BASE}/api/documents/${documentId}/sections/${sectionKey}`,
  );
  return handleResponse(res);
}

export async function getSourceIndex(id: string): Promise<SourceIndex> {
  const res = await fetch(`${API_BASE}/api/documents/${id}/source-index`);
  return handleResponse(res);
}

export function pdfUrl(documentId: string): string {
  return `${API_BASE}/api/documents/${documentId}/pdf`;
}

export async function listPdfHandlers(): Promise<PdfHandlerInfo[]> {
  const res = await fetch(`${API_BASE}/api/pdf-handlers`);
  return handleResponse(res);
}

export async function askDocument(
  documentId: string,
  question: string,
  history: ChatMessage[],
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/api/documents/${documentId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, history }),
  });
  return handleResponse(res);
}

export async function uploadDocument(
  file: File,
  pdfHandler: string,
): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  form.append("pdf_handler", pdfHandler);
  const res = await fetch(`${API_BASE}/api/documents`, {
    method: "POST",
    body: form,
  });
  return handleResponse(res);
}
