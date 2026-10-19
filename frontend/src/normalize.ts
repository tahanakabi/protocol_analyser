import type { ResolvedSource, SourcedText } from "./types";

export function normalizeSourced(item: unknown): SourcedText {
  if (typeof item === "string") {
    return { text: item, sources: [], evidence_valid: false };
  }
  if (!item || typeof item !== "object") {
    return { text: "", sources: [], evidence_valid: false };
  }
  const o = item as Record<string, unknown>;
  const sources = Array.isArray(o.sources)
    ? o.sources.map((s) => normalizeSource(s))
    : [];
  return {
    text: typeof o.text === "string" ? o.text : String(o.text ?? ""),
    sources,
    evidence_valid: Boolean(o.evidence_valid),
  };
}

function normalizeSource(raw: unknown): ResolvedSource {
  if (!raw || typeof raw !== "object") {
    return { block_id: "", page: 0, bbox: [], quote: "", quote_matched: false };
  }
  const s = raw as Record<string, unknown>;
  return {
    block_id: String(s.block_id ?? ""),
    page: Number(s.page ?? 0),
    bbox: Array.isArray(s.bbox) ? s.bbox.map(Number) : [],
    quote: String(s.quote ?? ""),
    quote_matched: Boolean(s.quote_matched),
  };
}

export function normalizeSourcedList(items: unknown): SourcedText[] {
  if (!Array.isArray(items)) return [];
  return items.map(normalizeSourced);
}
