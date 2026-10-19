import { useCallback, useEffect, useRef, useState } from "react";
import { getDocument, getSection } from "../api";
import { normalizeSourced, normalizeSourcedList } from "../normalize";
import type {
  AssessmentProcedure,
  Endpoints,
  ProtocolExtraction,
  ScheduleOfActivities,
  SectionsManifest,
  StudyObjectives,
  ValidationSummary,
  VisitDefinition,
} from "../types";

const SECTION_KEYS = [
  "study_objectives",
  "endpoints",
  "schedule_of_activities",
  "inclusion_criteria",
  "exclusion_criteria",
  "visits",
  "key_assessments_and_procedures",
  "safety_monitoring_rules",
  "extraction_notes",
  "validation",
] as const;

export type SectionKey = (typeof SECTION_KEYS)[number];

function normalizeVisit(raw: unknown): VisitDefinition {
  const v = raw as Record<string, unknown>;
  return {
    name: normalizeSourced(v.name),
    timing: normalizeSourced(v.timing),
    window: v.window ? normalizeSourced(v.window) : null,
    notes: v.notes ? normalizeSourced(v.notes) : null,
  };
}

function normalizeAssessment(raw: unknown): AssessmentProcedure {
  const a = raw as Record<string, unknown>;
  return {
    name: normalizeSourced(a.name),
    description: a.description ? normalizeSourced(a.description) : null,
    visit_or_timepoint: a.visit_or_timepoint
      ? normalizeSourced(a.visit_or_timepoint)
      : null,
  };
}

export function useDocumentSections(documentId: string | null) {
  const [manifest, setManifest] = useState<SectionsManifest | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<Partial<ProtocolExtraction>>({});
  const loadedRef = useRef<Set<string>>(new Set());

  const loadSection = useCallback(
    async (key: SectionKey) => {
      if (!documentId || loadedRef.current.has(key)) return;
      try {
        const payload = await getSection(documentId, key);
        loadedRef.current.add(key);
        setData((prev) => {
          const next = { ...prev };
          switch (key) {
            case "study_objectives": {
              const so = payload as StudyObjectives;
              next.study_objectives = {
                primary: normalizeSourcedList(so.primary),
                secondary: normalizeSourcedList(so.secondary),
              };
              break;
            }
            case "endpoints": {
              const ep = payload as Endpoints;
              next.endpoints = {
                primary: normalizeSourcedList(ep.primary),
                secondary: normalizeSourcedList(ep.secondary),
                exploratory: normalizeSourcedList(ep.exploratory),
              };
              break;
            }
            case "schedule_of_activities": {
              const soa = payload as Partial<ScheduleOfActivities>;
              next.schedule_of_activities = {
                title: soa.title ?? "Schedule of Activities",
                schedules: Array.isArray(soa.schedules) ? soa.schedules : [],
                summary: typeof soa.summary === "string" ? soa.summary : "",
                source_pages: soa.source_pages ?? [],
                notes: soa.notes ?? null,
                confidence: soa.confidence ?? "low",
                structural_valid: Boolean(soa.structural_valid),
              };
              break;
            }
            case "inclusion_criteria":
              next.inclusion_criteria = normalizeSourcedList(payload);
              break;
            case "exclusion_criteria":
              next.exclusion_criteria = normalizeSourcedList(payload);
              break;
            case "visits":
              next.visits = Array.isArray(payload)
                ? payload.map(normalizeVisit)
                : [];
              break;
            case "key_assessments_and_procedures":
              next.key_assessments_and_procedures = Array.isArray(payload)
                ? payload.map(normalizeAssessment)
                : [];
              break;
            case "safety_monitoring_rules":
              next.safety_monitoring_rules = payload
                ? normalizeSourcedList(payload)
                : null;
              break;
            case "extraction_notes":
              next.extraction_notes = payload
                ? normalizeSourced(payload)
                : null;
              break;
            case "validation":
              next.validation = payload as ValidationSummary;
              break;
          }
          return next;
        });
      } catch {
        // section not ready yet
      }
    },
    [documentId],
  );

  const refresh = useCallback(async () => {
    if (!documentId) return;
    try {
      const detail = await getDocument(documentId);
      setStatus(detail.meta.status);
      setError(detail.meta.error ?? null);
      if (detail.sections?.sections) {
        setManifest(detail.sections);
        for (const key of SECTION_KEYS) {
          if (detail.sections.sections[key] === "completed") {
            await loadSection(key);
          }
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load document");
    }
  }, [documentId, loadSection]);

  useEffect(() => {
    loadedRef.current = new Set();
    setData({});
    setManifest(null);
    if (!documentId) return;
    refresh();
    const id = window.setInterval(refresh, 2000);
    return () => window.clearInterval(id);
  }, [documentId, refresh]);

  const sectionState = (key: SectionKey) =>
    manifest?.sections?.[key] ?? "pending";

  return { manifest, status, error, data, sectionState, refresh };
}
