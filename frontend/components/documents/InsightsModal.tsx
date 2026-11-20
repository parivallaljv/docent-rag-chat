"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { getDocumentInsight } from "@/lib/api";
import type { InsightKind, InsightResponse, QuizResult } from "@/lib/types";

interface InsightsModalProps {
  documentId: string;
  filename: string;
  kind: InsightKind;
  onClose: () => void;
}

const TITLES: Record<InsightKind, string> = {
  summary: "Summary",
  key_facts: "Key facts",
  quiz: "Quiz",
};

function PageTag({ page }: { page: number | null }) {
  if (page == null) return null;
  return (
    <span className="ml-2 shrink-0 rounded bg-surface-muted px-1.5 py-0.5 text-xs font-medium text-muted">
      p. {page}
    </span>
  );
}

export default function InsightsModal({
  documentId,
  filename,
  kind,
  onClose,
}: InsightsModalProps) {
  const [data, setData] = useState<InsightResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // Bumped on every (re)generation so the quiz state resets with new content.
  const [generation, setGeneration] = useState(0);

  const load = useCallback(
    async (refresh: boolean) => {
      setIsLoading(true);
      setFailed(false);
      try {
        const res = await getDocumentInsight(documentId, kind, refresh);
        setData(res);
        setGeneration((g) => g + 1);
      } catch (err) {
        setFailed(true);
        toast.error(err instanceof Error ? err.message : "Couldn't generate insights.");
      } finally {
        setIsLoading(false);
      }
    },
    [documentId, kind]
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(false);
  }, [load]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${TITLES[kind]} for ${filename}`}
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-surface shadow-card"
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 className="font-heading text-lg font-semibold text-foreground">
              {TITLES[kind]}
            </h2>
            <p className="truncate text-xs text-muted">{filename}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-muted"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 text-sm text-foreground">
          {isLoading ? (
            <div className="space-y-2" aria-busy="true">
              <p className="flex items-center gap-2 text-muted">
                <span className="material-symbols-outlined animate-spin text-[18px]">
                  progress_activity
                </span>
                Generating {TITLES[kind].toLowerCase()}…
              </p>
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-4 animate-pulse rounded bg-surface-muted" />
              ))}
            </div>
          ) : failed || !data ? (
            <p className="text-muted">Nothing to show. Try regenerating.</p>
          ) : data.kind === "summary" ? (
            <div className="space-y-3">
              <p className="leading-relaxed">{data.result.summary}</p>
              <ul className="list-disc space-y-1 pl-5">
                {data.result.bullets.map((b, i) => (
                  <li key={i} className="leading-relaxed">
                    {b}
                  </li>
                ))}
              </ul>
            </div>
          ) : data.kind === "key_facts" ? (
            <ul className="space-y-2">
              {data.result.facts.map((f, i) => (
                <li key={i} className="flex items-start justify-between rounded-lg bg-surface-muted/60 px-3 py-2">
                  <span className="leading-relaxed">{f.fact}</span>
                  <PageTag page={f.page} />
                </li>
              ))}
            </ul>
          ) : (
            <Quiz key={generation} result={data.result} />
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <span className="text-xs text-muted">
            {!isLoading && data?.cached ? "Cached result" : ""}
          </span>
          <button
            type="button"
            onClick={() => void load(true)}
            disabled={isLoading}
            className="flex items-center gap-1 rounded-lg bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            <span className="material-symbols-outlined text-[16px]">refresh</span>
            Regenerate
          </button>
        </div>
      </div>
    </div>
  );
}

function Quiz({ result }: { result: QuizResult }) {
  const [picked, setPicked] = useState<Record<number, number>>({});
  const total = result.questions.length;
  const answered = Object.keys(picked).length;
  const score = result.questions.filter((q, i) => picked[i] === q.answer_index).length;

  return (
    <div className="space-y-5">
      <p className="text-xs font-semibold text-muted">
        Score: {score} / {answered} answered ({total} questions)
      </p>
      {result.questions.map((q, qi) => {
        const choice = picked[qi];
        const revealed = choice !== undefined;
        return (
          <div key={qi} className="space-y-2">
            <p className="font-medium">
              {qi + 1}. {q.question}
              <PageTag page={q.page} />
            </p>
            <div className="space-y-1.5">
              {q.options.map((opt, oi) => {
                const isCorrect = oi === q.answer_index;
                const isPicked = oi === choice;
                const style = !revealed
                  ? "bg-surface-muted hover:bg-surface-muted/70"
                  : isCorrect
                    ? "bg-success/10 text-success"
                    : isPicked
                      ? "bg-danger/10 text-danger"
                      : "bg-surface-muted/50 text-muted";
                return (
                  <button
                    key={oi}
                    type="button"
                    disabled={revealed}
                    onClick={() => setPicked((p) => ({ ...p, [qi]: oi }))}
                    className={`block w-full rounded-lg px-3 py-2 text-left transition-colors disabled:cursor-default ${style}`}
                  >
                    {opt}
                  </button>
                );
              })}
            </div>
            {revealed && (
              <p className="text-xs leading-relaxed text-muted">
                {choice === q.answer_index ? "Correct. " : "Incorrect. "}
                {q.explanation}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
