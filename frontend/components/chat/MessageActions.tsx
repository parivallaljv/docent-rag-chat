"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { submitFeedback } from "@/lib/api";
import {
  isSpeechSynthesisSupported,
  markdownToSpeech,
  useSpeechSynthesisSupported,
} from "@/lib/speech";
import type { CritiqueClaim, ProposalDecision } from "@/lib/types";
import type { MessageProposal } from "./ChatWindow";

const actionClass =
  "inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-muted transition-colors hover:bg-background hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50";

interface MessageActionsProps {
  content: string;
  messageId?: string;
  onExport: () => void;
}

export default function MessageActions({ content, messageId, onExport }: MessageActionsProps) {
  const canSpeak = useSpeechSynthesisSupported();
  const [speaking, setSpeaking] = useState(false);
  const [rating, setRating] = useState<1 | -1 | null>(null);
  const [askComment, setAskComment] = useState(false);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    return () => {
      if (speaking && isSpeechSynthesisSupported()) window.speechSynthesis.cancel();
    };
  }, [speaking]);

  function toggleSpeak() {
    if (!isSpeechSynthesisSupported()) return;
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    const text = markdownToSpeech(content);
    if (!text) return;
    synth.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    setSpeaking(true);
    synth.speak(utterance);
  }

  async function sendFeedback(value: 1 | -1, text?: string) {
    if (!messageId || busy) return;
    setBusy(true);
    try {
      await submitFeedback(messageId, value, text);
      setRating(value);
      setAskComment(false);
      setComment("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't save your feedback.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-0.5">
        {messageId && (
          <>
            <button
              type="button"
              aria-label="Good answer"
              aria-pressed={rating === 1}
              disabled={busy}
              onClick={() => {
                setAskComment(false);
                void sendFeedback(1);
              }}
              className={`${actionClass} ${rating === 1 ? "!text-primary" : ""}`}
            >
              <span
                className="material-symbols-outlined text-[16px]"
                style={{ fontVariationSettings: `'FILL' ${rating === 1 ? 1 : 0}` }}
              >
                thumb_up
              </span>
            </button>
            <button
              type="button"
              aria-label="Bad answer"
              aria-pressed={rating === -1}
              disabled={busy}
              onClick={() => setAskComment((open) => !open)}
              className={`${actionClass} ${rating === -1 ? "!text-danger" : ""}`}
            >
              <span
                className="material-symbols-outlined text-[16px]"
                style={{ fontVariationSettings: `'FILL' ${rating === -1 ? 1 : 0}` }}
              >
                thumb_down
              </span>
            </button>
            <span className="mx-1 h-4 w-px bg-border" />
          </>
        )}
        {canSpeak && (
          <button type="button" onClick={toggleSpeak} className={actionClass}>
            <span className="material-symbols-outlined text-[16px]">
              {speaking ? "stop_circle" : "volume_up"}
            </span>
            {speaking ? "Stop" : "Listen"}
          </button>
        )}
        <button type="button" onClick={onExport} className={actionClass}>
          <span className="material-symbols-outlined text-[16px]">download</span>
          Export
        </button>
      </div>

      {askComment && (
        <form
          className="mt-1.5 flex items-center gap-1.5"
          onSubmit={(event) => {
            event.preventDefault();
            void sendFeedback(-1, comment);
          }}
        >
          <input
            type="text"
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            maxLength={1000}
            placeholder="What went wrong? (optional)"
            className="min-w-0 flex-1 rounded-md bg-background px-2.5 py-1.5 text-xs text-foreground outline-none placeholder:text-muted focus:shadow-[0_0_0_2px_rgb(var(--primary))]"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-primary px-2.5 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary-hover disabled:opacity-60"
          >
            Send
          </button>
        </form>
      )}
    </div>
  );
}

export function FactCheck({ claims }: { claims: CritiqueClaim[] }) {
  const [open, setOpen] = useState(false);
  if (claims.length === 0) return null;
  const unsupported = claims.filter((c) => !c.supported).length;

  return (
    <div className="mt-2.5 rounded-lg bg-surface px-3 py-2 shadow-card">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-left text-xs font-medium text-foreground"
      >
        <span
          className={`material-symbols-outlined text-[16px] ${
            unsupported > 0 ? "text-warning" : "text-success"
          }`}
        >
          {unsupported > 0 ? "warning" : "fact_check"}
        </span>
        <span>Fact check</span>
        <span className="text-muted">
          {unsupported > 0
            ? `${unsupported} of ${claims.length} unsupported`
            : `${claims.length} supported`}
        </span>
        <span className="material-symbols-outlined ml-auto text-[16px] text-muted">
          {open ? "expand_less" : "expand_more"}
        </span>
      </button>
      {open && (
        <ul className="mt-2 space-y-1.5">
          {claims.map((c, i) => (
            <li
              key={i}
              className={`flex items-start gap-1.5 rounded-md px-2 py-1 text-xs leading-relaxed ${
                c.supported ? "" : "bg-warning/10"
              }`}
            >
              <span
                className={`material-symbols-outlined mt-px text-[14px] ${
                  c.supported ? "text-success" : "text-warning"
                }`}
                aria-label={c.supported ? "Supported" : "Unsupported"}
              >
                {c.supported ? "check_circle" : "warning"}
              </span>
              <span>
                {c.claim}
                {c.excerpt != null && <span className="ml-1 text-muted">[{c.excerpt}]</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PROPOSAL_RESULT_LABEL = {
  saved: "Saved",
  rejected: "Dismissed",
  expired: "Expired",
  failed: "Couldn't save",
} as const;

export function MemoryProposalCard({
  proposal,
  onDecide,
}: {
  proposal: MessageProposal;
  onDecide: (decision: ProposalDecision) => void;
}) {
  const sending = proposal.status === "sending";

  return (
    <div className="mt-2.5 rounded-lg bg-surface px-3 py-2 shadow-card">
      <p className="flex items-start gap-1.5 text-xs leading-relaxed text-foreground">
        <span className="material-symbols-outlined mt-px text-[14px] text-primary">bookmark_add</span>
        <span>
          <span className="font-medium">Save to memory?</span> {proposal.text}
        </span>
      </p>
      <div className="mt-2 flex items-center gap-2">
        {proposal.status === "pending" || proposal.status === "sending" ? (
          <>
            <button
              type="button"
              disabled={sending}
              onClick={() => onDecide("approve")}
              className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary-hover disabled:cursor-not-allowed disabled:opacity-60"
            >
              Approve
            </button>
            <button
              type="button"
              disabled={sending}
              onClick={() => onDecide("reject")}
              className={`${actionClass} bg-background`}
            >
              Dismiss
            </button>
          </>
        ) : (
          <span
            role="status"
            className={`text-xs font-medium ${
              proposal.status === "saved"
                ? "text-success"
                : proposal.status === "failed"
                  ? "text-danger"
                  : "text-muted"
            }`}
          >
            {PROPOSAL_RESULT_LABEL[proposal.status]}
          </span>
        )}
      </div>
    </div>
  );
}
