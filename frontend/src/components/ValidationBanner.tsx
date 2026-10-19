import type { ValidationSummary } from "../types";

export function ValidationBanner({ validation }: { validation: ValidationSummary }) {
  const total = validation.total_sourced_items ?? 0;
  const valid = validation.valid_items ?? 0;
  const invalid = validation.invalid_items ?? 0;
  const needsReview = Boolean(validation.needs_review);
  const cls = needsReview ? "banner-low" : "banner-high";
  return (
    <div className={`banner ${cls} validation-banner`}>
      <strong>Evidence validation</strong>
      <span>
        {valid} / {total} items with valid citations
        {invalid > 0 && ` (${invalid} need review)`}
      </span>
      <span className="muted">
        SoA structure: {validation.soa_structural_valid ? "OK" : "needs review"}
      </span>
      {needsReview && (
        <p className="validation-hint">
          Click &ldquo;p.N — quote&rdquo; links to jump to the PDF and highlight source regions.
        </p>
      )}
    </div>
  );
}
