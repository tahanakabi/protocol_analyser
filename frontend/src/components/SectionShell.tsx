import type { ReactNode } from "react";
import type { SectionStatus } from "../types";

export function SectionShell({
  title,
  status,
  error,
  children,
}: {
  title: string;
  status: SectionStatus;
  error?: string;
  children: ReactNode;
}) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>{title}</h2>
        <span className={`section-status section-status-${status}`}>{status}</span>
      </div>
      {error && <p className="error-inline">{error}</p>}
      {status === "completed" ? children : (
        <p className="muted">
          {status === "processing" ? "Extracting…" : status === "failed" ? "Failed." : "Waiting…"}
        </p>
      )}
    </section>
  );
}
