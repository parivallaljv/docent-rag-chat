"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { RealtimePostgresChangesPayload } from "@supabase/supabase-js";
import { toast } from "sonner";
import { getSupabaseBrowserClient } from "@/lib/supabaseClient";
import { retryDocument } from "@/lib/api";
import type { DocumentRecord, DocumentStatus, InsightKind } from "@/lib/types";
import InsightsModal from "./InsightsModal";

export default function DocumentList() {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [insight, setInsight] = useState<{ doc: DocumentRecord; kind: InsightKind } | null>(null);

  async function handleRetry(id: string) {
    try {
      const updated = await retryDocument(id);
      setDocuments((prev) => prev.map((doc) => (doc.id === id ? updated : doc)));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't retry this document.");
    }
  }

  useEffect(() => {
    const supabase = getSupabaseBrowserClient();
    let channel: ReturnType<typeof supabase.channel> | null = null;
    let isMounted = true;

    async function init() {
      const {
        data: { user },
      } = await supabase.auth.getUser();

      if (!isMounted) return;

      if (!user) {
        setError("Your session has expired. Please sign in again.");
        setIsLoading(false);
        return;
      }

      const { data, error: fetchError } = await supabase
        .from("documents")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false });

      if (!isMounted) return;

      if (fetchError) {
        setError(fetchError.message);
      } else {
        setDocuments((data ?? []) as DocumentRecord[]);
      }
      setIsLoading(false);

      // Live status updates (pending -> processing -> ready/failed) as the
      // backend ingests the document, instead of polling.
      channel = supabase
        .channel(`documents-changes-${user.id}`)
        .on(
          "postgres_changes",
          {
            event: "*",
            schema: "public",
            table: "documents",
            filter: `user_id=eq.${user.id}`,
          },
          (payload: RealtimePostgresChangesPayload<DocumentRecord>) => {
            if (!isMounted) return;

            if (payload.eventType === "INSERT") {
              const newDoc = payload.new as DocumentRecord;
              setDocuments((prev) =>
                prev.some((doc) => doc.id === newDoc.id)
                  ? prev
                  : [newDoc, ...prev]
              );
            } else if (payload.eventType === "UPDATE") {
              const updated = payload.new as DocumentRecord;
              const previous = payload.old as Partial<DocumentRecord> | undefined;

              // Only toast on a genuine transition INTO "failed" (compared
              // against this row's previous status), not merely because
              // the row's current status happens to be "failed" - avoids
              // re-toasting on unrelated updates to an already-failed row.
              if (
                updated.status === "failed" &&
                previous?.status !== "failed"
              ) {
                toast.error(
                  `${updated.filename} failed to process: ${
                    updated.error_message ?? "Unknown error."
                  }`
                );
              }

              setDocuments((prev) =>
                prev.map((doc) => (doc.id === updated.id ? updated : doc))
              );
            } else if (payload.eventType === "DELETE") {
              const deletedId = (payload.old as { id: string }).id;
              setDocuments((prev) =>
                prev.filter((doc) => doc.id !== deletedId)
              );
            }
          }
        )
        .subscribe();
    }

    init();

    return () => {
      isMounted = false;
      if (channel) supabase.removeChannel(channel);
    };
  }, []);

  if (isLoading) {
    return <SkeletonList />;
  }

  if (error) {
    return (
      <p className="rounded-lg bg-danger/10 px-3 py-2 text-sm text-danger">
        Couldn&apos;t load your documents: {error}
      </p>
    );
  }

  if (documents.length === 0) {
    return (
      <div className="rounded-2xl bg-surface px-6 py-12 text-center shadow-card">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-muted text-muted">
          <span className="material-symbols-outlined text-[28px]">folder_open</span>
        </div>
        <p className="mt-4 text-base font-semibold text-foreground">No documents yet</p>
        <p className="mx-auto mt-1 max-w-sm text-sm text-muted">
          Upload your first PDF above to get started.
        </p>
      </div>
    );
  }

  const filtered = filter.trim()
    ? documents.filter((doc) =>
        doc.filename.toLowerCase().includes(filter.trim().toLowerCase())
      )
    : documents;

  return (
    <div className="overflow-hidden rounded-2xl bg-surface shadow-card">
      <div className="flex flex-col gap-3 border-b border-border p-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 sm:max-w-xs">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-[18px] text-muted">
            search
          </span>
          <input
            type="text"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter documents…"
            className="w-full rounded-lg bg-surface-muted py-2 pl-10 pr-3 text-sm text-foreground outline-none placeholder:text-muted focus:bg-background focus:shadow-[0_0_0_2px_rgb(var(--primary))]"
          />
        </div>
        <span className="shrink-0 rounded-lg bg-surface-muted px-2.5 py-1 text-xs font-semibold text-muted">
          {documents.length} document{documents.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="divide-y divide-border">
        {filtered.map((doc) => (
          <li
            key={doc.id}
            className="flex items-center justify-between gap-4 px-4 py-4 transition-colors hover:bg-surface-muted/50 sm:px-5"
          >
            <div className="flex min-w-0 items-center gap-3">
              <div
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${statusIconClasses(
                  doc.status
                )}`}
              >
                <span className="material-symbols-outlined text-[20px]">
                  {statusIcon(doc.status)}
                </span>
              </div>
              <div className="min-w-0">
                <p className="truncate text-base font-medium text-foreground">
                  {doc.filename}
                </p>
                <p className="mt-0.5 text-xs text-muted">
                  {new Date(doc.created_at).toLocaleString()}
                  {doc.page_count ? ` · ${doc.page_count} pages` : ""}
                </p>
                {doc.status === "failed" && doc.error_message && (
                  <p className="mt-0.5 flex items-center gap-1 text-xs text-danger">
                    <span className="material-symbols-outlined text-[14px]">warning</span>
                    {doc.error_message}
                  </p>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <StatusBadge status={doc.status} />
              {doc.status === "ready" && (
                <div className="hidden items-center gap-1 sm:flex">
                  {INSIGHT_ACTIONS.map(({ kind, label }) => (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => setInsight({ doc, kind })}
                      className="rounded-lg bg-surface-muted px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {doc.status === "failed" && (
                <button
                  type="button"
                  onClick={() => handleRetry(doc.id)}
                  className="rounded-lg bg-surface-muted px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-primary/10 hover:text-primary"
                >
                  Retry
                </button>
              )}
              {doc.status === "ready" && (
                <Link
                  href={`/chat?documentId=${doc.id}`}
                  className="flex items-center gap-1 rounded-lg bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
                >
                  <span>Chat</span>
                  <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
                </Link>
              )}
            </div>
          </li>
        ))}
        {filtered.length === 0 && (
          <li className="px-5 py-8 text-center text-sm text-muted">
            No documents match &ldquo;{filter}&rdquo;.
          </li>
        )}
      </ul>
      {insight && (
        <InsightsModal
          documentId={insight.doc.id}
          filename={insight.doc.filename}
          kind={insight.kind}
          onClose={() => setInsight(null)}
        />
      )}
    </div>
  );
}

const INSIGHT_ACTIONS: { kind: InsightKind; label: string }[] = [
  { kind: "summary", label: "Summary" },
  { kind: "key_facts", label: "Key facts" },
  { kind: "quiz", label: "Quiz" },
];

const STATUS_CONFIG: Record<
  DocumentStatus,
  { label: string; className: string; pulse?: boolean }
> = {
  pending: {
    label: "Pending",
    className: "bg-surface-muted text-muted",
    pulse: true,
  },
  processing: {
    label: "Processing",
    className: "bg-warning/10 text-warning",
    pulse: true,
  },
  ready: { label: "Ready", className: "bg-success/10 text-success" },
  failed: { label: "Failed", className: "bg-danger/10 text-danger" },
};

function statusIcon(status: DocumentStatus): string {
  switch (status) {
    case "ready":
      return "description";
    case "processing":
    case "pending":
      return "sync";
    case "failed":
      return "error";
  }
}

function statusIconClasses(status: DocumentStatus): string {
  switch (status) {
    case "ready":
      return "bg-primary/10 text-primary";
    case "processing":
    case "pending":
      return "bg-warning/10 text-warning";
    case "failed":
      return "bg-danger/10 text-danger";
  }
}

function StatusBadge({ status }: { status: DocumentStatus }) {
  const { label, className, pulse } = STATUS_CONFIG[status];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${className}`}
    >
      {pulse && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {label}
    </span>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-2">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-16 animate-pulse rounded-2xl bg-surface-muted" />
      ))}
    </div>
  );
}
