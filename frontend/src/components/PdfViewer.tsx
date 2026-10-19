import { useMemo } from "react";
import type { PdfHighlight } from "../types";

/**
 * Native browser PDF rendering (no PDF.js worker). Avoids Vite/worker version
 * mismatches. Page jumps use the #page= fragment; highlights are shown as text.
 */
export function PdfViewer({
  url,
  highlights,
  activePage,
}: {
  url: string;
  highlights: PdfHighlight[];
  activePage: number;
}) {
  const page = Math.max(1, activePage);
  const iframeSrc = useMemo(() => `${url}#page=${page}`, [url, page]);

  const pageHighlights = highlights.filter((h) => h.page === page);

  return (
    <div className="pdf-viewer">
      <iframe
        key={iframeSrc}
        title="Protocol PDF"
        className="pdf-iframe"
        src={iframeSrc}
      />
      <p className="muted pdf-page-label">Showing page {page}</p>
      {pageHighlights.length > 0 && (
        <div className="pdf-citation-callout">
          <strong>Source on this page</strong>
          <ul>
            {pageHighlights.map((h, i) => (
              <li key={i}>
                {h.label ? `“${h.label}”` : "Highlighted region"}
                {h.bbox.length >= 4 && (
                  <span className="muted"> (bbox in protocol coordinates)</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
