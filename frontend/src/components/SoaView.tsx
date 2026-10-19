import { useState } from "react";
import type {
  PdfHighlight,
  ScheduleOfActivities,
  SoaActivity,
  SoaSchedule,
  SoaVisit,
} from "../types";

type View = "structured" | "summary" | "json";

const VIEWS: { id: View; label: string }[] = [
  { id: "structured", label: "Structured" },
  { id: "summary", label: "Text summary" },
  { id: "json", label: "JSON" },
];

export function SoaView({
  soa,
  onInspect,
}: {
  soa: ScheduleOfActivities;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const [view, setView] = useState<View>("structured");
  const showBanner =
    soa.confidence === "low" || !soa.structural_valid || Boolean(soa.notes);

  if (!soa.schedules.length) {
    return (
      <section className="section">
        {soa.notes && <div className="banner banner-low">{soa.notes}</div>}
        <p className="muted">
          No schedule extracted. Documents processed before the JSON schedule format
          need the schedule of activities re-extracted.
        </p>
      </section>
    );
  }

  const text = view === "json" ? JSON.stringify(soa.schedules, null, 2) : soa.summary;

  return (
    <section className="section">
      {showBanner && (
        <div className={`banner banner-${soa.confidence}`}>
          {soa.confidence === "low" && <strong>Low confidence SoA extraction. </strong>}
          {!soa.structural_valid && <strong>Needs review. </strong>}
          {soa.notes && <span>{soa.notes}</span>}
        </div>
      )}
      <div className="soa-toolbar">
        <div className="soa-tabs" role="tablist">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              role="tab"
              aria-selected={view === v.id}
              className={view === v.id ? "active" : ""}
              onClick={() => setView(v.id)}
            >
              {v.label}
            </button>
          ))}
        </div>
        {view !== "structured" && (
          <button type="button" onClick={() => void navigator.clipboard.writeText(text)}>
            Copy
          </button>
        )}
        {soa.source_pages.length > 0 && (
          <span className="muted">pages {soa.source_pages.join(", ")}</span>
        )}
      </div>
      {view === "structured" ? (
        soa.schedules.map((schedule, i) => (
          <ScheduleCard key={i} schedule={schedule} onInspect={onInspect} />
        ))
      ) : (
        <pre className="soa-text">{text}</pre>
      )}
    </section>
  );
}

function ScheduleCard({
  schedule,
  onInspect,
}: {
  schedule: SoaSchedule;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const heading = [schedule.table_label, schedule.title].filter(Boolean).join(" – ");
  return (
    <div className="card soa-schedule">
      <h3>{heading || "Schedule"}</h3>
      <p className="muted">
        {schedule.pages.length > 0 && <>Pages {schedule.pages.join(", ")}. </>}
        {schedule.population && <>Population: {schedule.population}.</>}
      </p>

      <h4>Visits ({schedule.visits.length})</h4>
      <ul className="soa-visits">
        {schedule.visits.map((visit, i) => (
          <li key={i}>{visitText(visit)}</li>
        ))}
      </ul>

      <h4>Activities ({schedule.activities.length})</h4>
      {groupByCategory(schedule.activities).map(([category, activities]) => (
        <div key={category} className="soa-category">
          {category && <h5>{category}</h5>}
          <ul className="soa-activities">
            {activities.map((activity, i) => (
              <ActivityItem key={i} activity={activity} onInspect={onInspect} />
            ))}
          </ul>
        </div>
      ))}

      {schedule.footnotes.length > 0 && (
        <>
          <h4>Footnotes</h4>
          <ul className="soa-footnotes">
            {schedule.footnotes.map((note, i) => (
              <li key={i}>
                <strong>{note.marker}</strong> {note.text}
              </li>
            ))}
          </ul>
        </>
      )}
      {schedule.abbreviations.length > 0 && (
        <p className="muted">Abbreviations: {schedule.abbreviations.join("; ")}</p>
      )}
    </div>
  );
}

function ActivityItem({
  activity,
  onInspect,
}: {
  activity: SoaActivity;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const inspect = () => {
    const page = activity.page > 0 ? activity.page : 1;
    const highlights =
      activity.bbox && activity.bbox.length >= 4
        ? [{ page, bbox: activity.bbox, label: activity.name }]
        : [];
    onInspect(highlights, page);
  };
  const occurrences = activity.occurrences.length
    ? activity.occurrences
        .map((o) => (o.detail ? `${o.visit} (${o.detail})` : o.visit))
        .join(", ")
    : "no visits marked";

  return (
    <li className={activity.found_on_page ? "" : "evidence-bad"}>
      <button type="button" className="source-link soa-activity-name" onClick={inspect}>
        {activity.name}
      </button>{" "}
      <span>{occurrences}</span>
      {activity.section_reference && (
        <span className="muted"> · Section {activity.section_reference}</span>
      )}
      {activity.note && <div className="muted">{activity.note}</div>}
      {activity.footnotes.map((note, i) => (
        <div key={i} className="muted soa-note">
          {note}
        </div>
      ))}
      {!activity.found_on_page && (
        <div className="evidence-badge bad">not found on p.{activity.page}</div>
      )}
      {activity.unknown_visits.length > 0 && (
        <div className="evidence-badge bad">
          unknown visits: {activity.unknown_visits.join(", ")}
        </div>
      )}
    </li>
  );
}

function visitText(visit: SoaVisit): string {
  const parts = [visit.label];
  if (visit.timing && visit.timing !== visit.label) parts.push(visit.timing);
  if (visit.window) parts.push(`window ${visit.window}`);
  if (visit.visit_type) parts.push(visit.visit_type);
  const head = parts.length > 1 ? `${parts[0]} (${parts.slice(1).join("; ")})` : parts[0];
  return visit.notes.length ? `${head} — ${visit.notes.join(" ")}` : head;
}

function groupByCategory(activities: SoaActivity[]): [string, SoaActivity[]][] {
  const groups = new Map<string, SoaActivity[]>();
  for (const activity of activities) {
    const key = activity.category ?? "";
    groups.set(key, [...(groups.get(key) ?? []), activity]);
  }
  return [...groups.entries()];
}
