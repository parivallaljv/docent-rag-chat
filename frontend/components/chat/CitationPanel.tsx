"use client";

import { useState } from "react";
import type { ChatCitation } from "@/lib/types";
import RelevanceGauge, { confidenceLabel } from "./RelevanceGauge";

interface CitationPanelProps {
  citations: ChatCitation[] | null;
}

const SNIPPET_PREVIEW_LENGTH = 160;

export default function CitationPanel({ citations }: CitationPanelProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <aside className="flex h-full flex-col rounded-xl bg-surface p-3 shadow-card">
      <div className="flex items-start justify-between px-2 pb-3 pt-1">
        <div>
          <h2 className="font-heading text-base font-semibold text-foreground">
            Sources &amp; Citations
          </h2>
          <p className="mt-0.5 text-xs text-muted">
            Passages the answer was grounded in.
          </p>
        </div>
        <span className="material-symbols-outlined text-[20px] text-primary">verified</span>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto scrollbar-thin px-1 pb-1">
        {!citations || citations.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-xl bg-surface-muted px-4 py-10 text-center">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-surface text-muted">
              <span className="material-symbols-outlined text-[18px]">ads_click</span>
            </div>
            <p className="text-sm text-muted">
              Citations for the selected answer will appear here.
            </p>
          </div>
        ) : (
          citations.map((citation) => {
            const isExpanded = expandedId === citation.id;
            const isLong = citation.snippet.length > SNIPPET_PREVIEW_LENGTH;
            const displayText =
              isExpanded || !isLong
                ? citation.snippet
                : `${citation.snippet.slice(0, SNIPPET_PREVIEW_LENGTH).trimEnd()}…`;

            return (
              <article
                key={citation.id}
                className="rounded-xl bg-surface-muted p-3.5 transition-colors hover:bg-surface-muted/70"
              >
                <div className="flex items-center justify-between gap-2">
                  <span
                    className="flex min-w-0 items-center gap-1.5 truncate text-sm font-medium text-foreground"
                    title={citation.filename}
                  >
                    <span className="material-symbols-outlined shrink-0 text-[16px] text-primary">
                      description
                    </span>
                    <span className="truncate">{citation.filename}</span>
                  </span>
                  <span className="shrink-0 rounded bg-surface px-2 py-0.5 text-xs font-medium text-muted">
                    p. {citation.page}
                  </span>
                </div>

                <div className="mt-2.5 flex items-center justify-between rounded-lg bg-surface px-2.5 py-2">
                  <div className="flex items-center gap-2">
                    <RelevanceGauge score={citation.similarity} />
                    <span className="text-xs font-medium text-foreground">
                      {confidenceLabel(citation.similarity)}
                    </span>
                  </div>
                  <span className="font-mono text-[10px] font-semibold uppercase tracking-wide text-primary">
                    {Math.round(citation.similarity * 100)}% match
                  </span>
                </div>

                <blockquote className="mt-2.5 rounded-lg bg-surface/60 p-2.5 text-sm leading-relaxed text-muted">
                  &ldquo;{displayText}&rdquo;
                </blockquote>

                {isLong && (
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedId((current) =>
                        current === citation.id ? null : citation.id
                      )
                    }
                    aria-expanded={isExpanded}
                    className="mt-1.5 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    {isExpanded ? "Show less" : "Show more"}
                  </button>
                )}
              </article>
            );
          })
        )}
      </div>
    </aside>
  );
}
