"use client";

import { useEffect, useState } from "react";
import { getDocuments } from "@/lib/api";
import type { DocumentRecord } from "@/lib/types";
import CompareModal from "./CompareModal";

export default function CompareButton() {
  const [ready, setReady] = useState<DocumentRecord[]>([]);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function load() {
      getDocuments()
        .then((docs) => {
          if (!cancelled) setReady(docs.filter((d) => d.status === "ready"));
        })
        .catch(() => {
          // Non-fatal: the button simply stays disabled.
        });
    }
    load();
    window.addEventListener("focus", load);
    return () => {
      cancelled = true;
      window.removeEventListener("focus", load);
    };
  }, []);

  const enabled = ready.length >= 2;

  return (
    <>
      <button
        type="button"
        disabled={!enabled}
        onClick={() => setOpen(true)}
        title={enabled ? "Compare two documents" : "Needs at least two ready documents"}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-surface px-3 py-2 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="material-symbols-outlined text-[18px] text-primary">compare_arrows</span>
        Compare
      </button>
      {open && <CompareModal documents={ready} onClose={() => setOpen(false)} />}
    </>
  );
}
