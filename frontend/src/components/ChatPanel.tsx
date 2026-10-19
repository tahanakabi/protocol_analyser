import { useEffect, useRef, useState } from "react";
import { askDocument } from "../api";
import type { ChatMessage, ChatResponse, ChatSource, PdfHighlight } from "../types";

interface Turn {
  question: string;
  answer?: string;
  sources?: ChatSource[];
  retrieval?: ChatResponse["retrieval"];
  error?: string;
}

const CITATION_RE = /\[(p\d+_b\d+)\]/g;

const EXAMPLES = [
  "Who is eligible to enrol?",
  "What is the dosing schedule?",
  "How are adverse events of special interest reported?",
];

export function ChatPanel({
  documentId,
  onInspect,
}: {
  documentId: string;
  onInspect: (highlights: PdfHighlight[], page: number) => void;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const pending = turns.length > 0 && turns[turns.length - 1].answer === undefined
    && !turns[turns.length - 1].error;
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [turns]);

  const ask = async (question: string) => {
    const q = question.trim();
    if (!q || pending) return;
    const history: ChatMessage[] = turns
      .filter((t) => t.answer)
      .flatMap((t) => [
        { role: "user" as const, content: t.question },
        { role: "assistant" as const, content: t.answer as string },
      ]);
    setDraft("");
    setTurns((prev) => [...prev, { question: q }]);
    try {
      const res = await askDocument(documentId, q, history);
      setTurns((prev) =>
        updateLast(prev, { answer: res.answer, sources: res.sources, retrieval: res.retrieval }),
      );
    } catch (e) {
      setTurns((prev) =>
        updateLast(prev, { error: e instanceof Error ? e.message : "Request failed" }),
      );
    }
  };

  const inspect = (source: ChatSource) =>
    onInspect([{ page: source.page, bbox: source.bbox, label: source.block_id }], source.page);

  return (
    <div className="chat-panel">
      <div className="chat-log">
        {turns.length === 0 && (
          <div className="chat-empty">
            <p className="muted">
              Ask a question about this protocol. Answers come only from the retrieved
              source blocks and cite them; click a citation to see it in the PDF.
            </p>
            <div className="chat-examples">
              {EXAMPLES.map((q) => (
                <button key={q} type="button" onClick={() => void ask(q)}>
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
        {turns.map((turn, i) => (
          <div key={i} className="chat-turn">
            <div className="chat-bubble chat-user">{turn.question}</div>
            {turn.error ? (
              <div className="chat-bubble chat-error">{turn.error}</div>
            ) : turn.answer === undefined ? (
              <div className="chat-bubble chat-assistant muted">Searching the protocol…</div>
            ) : (
              <div className="chat-bubble chat-assistant">
                <Answer text={turn.answer} sources={turn.sources ?? []} onCite={inspect} />
                <Sources
                  sources={turn.sources ?? []}
                  retrieval={turn.retrieval ?? "hybrid"}
                  onSelect={inspect}
                />
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void ask(draft);
        }}
      >
        <textarea
          value={draft}
          rows={2}
          placeholder="Ask about eligibility, visits, endpoints…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void ask(draft);
            }
          }}
        />
        <button type="submit" disabled={pending || !draft.trim()}>
          {pending ? "…" : "Ask"}
        </button>
      </form>
    </div>
  );
}

function updateLast(turns: Turn[], patch: Partial<Turn>): Turn[] {
  return turns.map((t, i) => (i === turns.length - 1 ? { ...t, ...patch } : t));
}

function Answer({
  text,
  sources,
  onCite,
}: {
  text: string;
  sources: ChatSource[];
  onCite: (source: ChatSource) => void;
}) {
  const byId = new Map(sources.map((s) => [s.block_id, s]));
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const match of text.matchAll(CITATION_RE)) {
    const index = match.index ?? 0;
    parts.push(text.slice(last, index));
    const source = byId.get(match[1]);
    parts.push(
      source ? (
        <button
          key={index}
          type="button"
          className="chat-cite"
          title={source.section_path ?? undefined}
          onClick={() => onCite(source)}
        >
          p.{source.page}
        </button>
      ) : null,
    );
    last = index + match[0].length;
  }
  parts.push(text.slice(last));
  return <div className="chat-answer">{parts}</div>;
}

function Sources({
  sources,
  retrieval,
  onSelect,
}: {
  sources: ChatSource[];
  retrieval: ChatResponse["retrieval"];
  onSelect: (source: ChatSource) => void;
}) {
  if (!sources.length) return null;
  const cited = sources.filter((s) => s.cited).length;
  return (
    <details className="chat-sources">
      <summary>
        {sources.length} retrieved blocks ({retrieval === "hybrid" ? "keyword + semantic" : "keyword only"}),{" "}
        {cited} cited
      </summary>
      <ul>
        {sources.map((s) => (
          <li key={s.block_id} className={s.cited ? "cited" : ""}>
            <button type="button" className="source-link" onClick={() => onSelect(s)}>
              p.{s.page} · {s.section_path ?? "no section"}
            </button>
            <span className="muted chat-ranks">
              {" "}
              keyword {s.keyword_rank ? `#${s.keyword_rank}` : "–"} · semantic{" "}
              {s.semantic_rank ? `#${s.semantic_rank}` : "–"}
            </span>
            <div className="muted chat-source-text">{s.text.slice(0, 240)}</div>
          </li>
        ))}
      </ul>
    </details>
  );
}
