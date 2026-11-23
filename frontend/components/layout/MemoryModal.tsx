"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import Modal from "@/components/common/Modal";
import { getMemory, saveMemory } from "@/lib/api";

const MAX_LENGTH = 2000;

export default function MemoryModal({ onClose }: { onClose: () => void }) {
  const [content, setContent] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMemory()
      .then((value) => {
        if (!cancelled) setContent(value);
      })
      .catch(() => {
        if (!cancelled) setUnavailable(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave() {
    setIsSaving(true);
    try {
      const saved = await saveMemory(content.trim());
      setContent(saved);
      toast.success(saved ? "Memory saved." : "Memory cleared.");
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save your memory.");
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal title="Memory" subtitle="Notes the assistant keeps in mind across chats" onClose={onClose}>
      {isLoading ? (
        <div className="h-24 animate-pulse rounded bg-surface-muted" aria-busy="true" />
      ) : unavailable ? (
        <p className="text-muted">Memory isn&apos;t available right now. Please try again later.</p>
      ) : (
        <div className="space-y-3">
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            maxLength={MAX_LENGTH}
            rows={8}
            placeholder="e.g. I'm a nurse; prefer short answers with bullet points."
            className="w-full resize-y rounded-lg bg-surface-muted p-3 text-sm text-foreground outline-none placeholder:text-muted focus:bg-background focus:shadow-[0_0_0_2px_rgb(var(--primary))]"
          />
          <div className="flex items-center justify-between">
            <span
              className={`text-xs font-medium ${
                content.length >= MAX_LENGTH ? "text-danger" : "text-muted"
              }`}
            >
              {content.length}/{MAX_LENGTH}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-surface-muted px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-background"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={isSaving}
                className="rounded-lg bg-primary px-4 py-1.5 text-sm font-semibold text-primary-foreground shadow-card transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
          <p className="text-xs text-muted">Leave empty and save to clear your memory.</p>
        </div>
      )}
    </Modal>
  );
}
