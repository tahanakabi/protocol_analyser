import { normalizeSourced, normalizeSourcedList } from "../normalize";
import type { PdfHighlight, ResolvedSource, SourcedText } from "../types";

export function SourcedTextList({
  items,
  empty,
  onInspect,
}: {
  items: SourcedText[] | unknown;
  empty: string;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const list = Array.isArray(items) ? normalizeSourcedList(items) : [];
  if (!list.length) return <p className="muted">{empty}</p>;

  return (
    <ul className="sourced-list">
      {list.map((item, i) => (
        <li key={i} className={item.evidence_valid ? "evidence-ok" : "evidence-bad"}>
          <div className="sourced-row">
            <span
              className={`evidence-badge ${item.evidence_valid ? "ok" : "bad"}`}
              title={
                item.evidence_valid
                  ? "Evidence validated against source blocks"
                  : "Evidence missing or quote mismatch"
              }
            >
              {item.evidence_valid ? "verified" : "review"}
            </span>
            <span>{item.text}</span>
          </div>
          {item.sources.length > 0 && (
            <div className="source-quotes">
              {item.sources.map((src, si) => (
                <button
                  type="button"
                  key={si}
                  className={`source-link ${src.quote_matched ? "" : "source-bad"}`}
                  onClick={() => inspectSource(src, onInspect)}
                >
                  p.{src.page} — &ldquo;{src.quote}&rdquo;
                </button>
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function inspectSource(
  src: ResolvedSource,
  onInspect: (highlights: PdfHighlight[], page: number) => void,
) {
  const page = src.page > 0 ? src.page : 1;
  if (!src.bbox || src.bbox.length < 4) {
    onInspect([], page);
    return;
  }
  onInspect([{ page, bbox: src.bbox, label: src.quote }], page);
}

export function SourcedNotes({
  item,
  onInspect,
}: {
  item: SourcedText | unknown;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const normalized = normalizeSourced(item);
  if (!normalized.text) return null;
  return (
    <div className="notes-box">
      <SourcedTextList items={[normalized]} empty="" onInspect={onInspect} />
    </div>
  );
}
