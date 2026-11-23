"use client";

import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import Modal from "@/components/common/Modal";
import { compareDocuments } from "@/lib/api";
import type { CompareResponse, DocumentRecord } from "@/lib/types";

export default function CompareModal({
  documents,
  onClose,
}: {
  documents: DocumentRecord[];
  onClose: () => void;
}) {
  const [a, setA] = useState(documents[0]?.id ?? "");
  const [b, setB] = useState(documents[1]?.id ?? "");
  const [topic, setTopic] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CompareResponse | null>(null);

  const canSubmit = a && b && a !== b && topic.trim().length > 0 && !isLoading;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!canSubmit) return;
    setIsLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await compareDocuments({ document_a: a, document_b: b, topic: topic.trim() })
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't compare these documents.";
      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  const selectClass =
    "w-full rounded-lg bg-surface-muted px-3 py-2 text-sm text-foreground outline-none focus:bg-background focus:shadow-[0_0_0_2px_rgb(var(--primary))]";

  return (
    <Modal
      title="Compare documents"
      subtitle="See how two documents differ on a topic"
      onClose={onClose}
      maxWidthClass="max-w-2xl"
    >
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-xs font-medium text-muted">
            Document A
            <select value={a} onChange={(e) => setA(e.target.value)} className={selectClass}>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-xs font-medium text-muted">
            Document B
            <select value={b} onChange={(e) => setB(e.target.value)} className={selectClass}>
              {documents.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.filename}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="block space-y-1 text-xs font-medium text-muted">
          Topic
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            maxLength={300}
            placeholder="e.g. payment terms"
            className={selectClass}
          />
        </label>
        <div className="flex items-center justify-between gap-3">
          {a === b ? (
            <span className="text-xs text-muted">Pick two different documents.</span>
          ) : (
            <span />
          )}
          <button
            type="submit"
            disabled={!canSubmit}
            className="rounded-lg bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground shadow-card transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {isLoading ? "Comparing…" : "Compare"}
          </button>
        </div>
      </form>

      {isLoading && (
        <div className="mt-4 space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-4 animate-pulse rounded bg-surface-muted" />
          ))}
        </div>
      )}

      {error && (
        <p className="mt-4 rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>
      )}

      {result && (
        <div className="mt-4 space-y-4">
          <ResultList title="Similarities" icon="join_inner" items={result.similarities} />
          <ResultList title="Differences" icon="compare_arrows" items={result.differences} />
          {result.sources.length > 0 && (
            <div>
              <h3 className="mb-1.5 font-heading text-sm font-semibold">Sources</h3>
              <ul className="space-y-2">
                {result.sources.map((s, i) => (
                  <li key={i} className="rounded-lg bg-surface-muted px-3 py-2">
                    <p className="text-xs font-medium text-muted">
                      {s.filename} · p. {s.page}
                    </p>
                    <p className="mt-0.5 text-xs leading-relaxed">{s.snippet}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}

function ResultList({ title, icon, items }: { title: string; icon: string; items: string[] }) {
  return (
    <div>
      <h3 className="mb-1.5 flex items-center gap-1.5 font-heading text-sm font-semibold">
        <span className="material-symbols-outlined text-[16px] text-primary">{icon}</span>
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="text-muted">None found.</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 leading-relaxed">
          {items.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
