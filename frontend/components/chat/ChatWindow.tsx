"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { getDocuments } from "@/lib/api";
import { prewarmChatSocket, sendChatMessage } from "@/lib/ws";
import type { ChatCitation, ChatHistoryTurn, DocumentRecord } from "@/lib/types";
import MessageStream from "./MessageStream";
import CitationPanel from "./CitationPanel";

export type MessageStatus =
  | "connecting"
  | "waking"
  | "streaming"
  | "done"
  | "error";

export interface ChatMessageState {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: MessageStatus;
  citations?: ChatCitation[];
  errorMessage?: string;
  /** Set for a connection/auth/quota-level failure (as opposed to a
   * backend-authored `error`/`no_context` message, which needs no special
   * framing beyond the message text itself). */
  errorKind?: "auth" | "quota_exceeded" | "connection";
}

interface ChatWindowProps {
  /** Restrict retrieval to a single document, or null to search across all. */
  documentId: string | null;
}

const MESSAGE_MAX_LENGTH = 4000;
const MESSAGE_LENGTH_WARNING_THRESHOLD = 3500;

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function ChatWindow({ documentId }: ChatWindowProps) {
  const [messages, setMessages] = useState<ChatMessageState[]>([]);
  const [draft, setDraft] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCitations, setActiveCitations] = useState<ChatCitation[] | null>(
    null
  );
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);

  const stopHandleRef = useRef<{ stop: () => void } | null>(null);

  useEffect(() => {
    let cancelled = false;
    getDocuments()
      .then((docs) => {
        if (!cancelled) setDocuments(docs);
      })
      .catch(() => {
        // Non-fatal: the document-scope selector just won't populate. The
        // chat input itself still works.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Open (and authenticate) the shared WebSocket connection as soon as
    // this page mounts, rather than waiting for the first message - by the
    // time the user finishes typing a question, the connection has often
    // already finished any cold-start wake-up in the background.
    prewarmChatSocket();
    return () => {
      stopHandleRef.current?.stop();
    };
  }, []);

  function updateMessage(
    id: string,
    updater: (message: ChatMessageState) => ChatMessageState
  ) {
    setMessages((prev) =>
      prev.map((message) => (message.id === id ? updater(message) : message))
    );
  }

  function handleShowCitations(message: ChatMessageState) {
    setActiveCitations(message.citations ?? []);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || isStreaming) return;

    const history: ChatHistoryTurn[] = messages
      .filter((message) => message.content.trim().length > 0)
      .map((message) => ({ role: message.role, content: message.content }));

    const userMessage: ChatMessageState = {
      id: createId(),
      role: "user",
      content: text,
    };
    const assistantId = createId();
    const assistantMessage: ChatMessageState = {
      id: assistantId,
      role: "assistant",
      content: "",
      status: "connecting",
    };

    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setDraft("");
    setIsStreaming(true);

    stopHandleRef.current = sendChatMessage(
      { message: text, documentId, history },
      {
        onWaking: () => {
          updateMessage(assistantId, (m) => ({ ...m, status: "waking" }));
        },
        onOpen: () => {
          updateMessage(assistantId, (m) => ({ ...m, status: "streaming" }));
        },
        onToken: (token) => {
          updateMessage(assistantId, (m) => ({
            ...m,
            status: "streaming",
            content: m.content + token,
          }));
        },
        onCitations: (citations) => {
          updateMessage(assistantId, (m) => ({
            ...m,
            status: "done",
            citations,
          }));
          setActiveCitations(citations);
        },
        onError: (message, kind) => {
          updateMessage(assistantId, (m) => {
            // No `kind` means a backend-authored SSE-equivalent `error` or
            // `no_context` message - already good, specific copy, render
            // inline unchanged, no toast.
            if (!kind) {
              return { ...m, status: "error", errorMessage: message };
            }

            // The backend's own quota message is already the friendly copy
            // we want; auth/connection failures get frontend-owned copy
            // since the raw message (e.g. "no session") isn't user-facing.
            const friendlyMessage =
              kind === "quota_exceeded"
                ? message
                : kind === "auth"
                  ? "Your session expired. Please sign in again."
                  : "Can't reach the server. Check your connection and try again.";

            toast.error(friendlyMessage);
            return {
              ...m,
              status: "error",
              errorMessage: friendlyMessage,
              errorKind: kind,
            };
          });
        },
        onStopped: () => {
          updateMessage(assistantId, (m) => ({ ...m, status: "done" }));
        },
        onTurnEnd: () => {
          setIsStreaming(false);
          stopHandleRef.current = null;
        },
      }
    );
  }

  function handleStop() {
    stopHandleRef.current?.stop();
  }

  const scopedDocument = documentId
    ? documents.find((doc) => doc.id === documentId)
    : undefined;

  return (
    <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-12">
      <div className="flex flex-col overflow-hidden rounded-xl bg-surface shadow-card lg:col-span-8">
        {documentId && (
          <div className="flex items-center justify-between gap-2 bg-surface-muted px-4 py-2.5 text-xs">
            <span className="flex items-center gap-1.5 text-muted">
              <span className="material-symbols-outlined text-[15px] text-primary">
                folder_open
              </span>
              Scoped to{" "}
              <span className="font-medium text-foreground">
                {scopedDocument?.filename ?? "this document"}
              </span>
            </span>
            <a href="/chat" className="font-medium text-primary hover:underline">
              Search all documents
            </a>
          </div>
        )}

        <MessageStream messages={messages} onShowCitations={handleShowCitations} />

        <div className="p-3">
          <form
            onSubmit={handleSubmit}
            className="flex flex-col gap-2 rounded-xl bg-surface-muted p-2.5 transition-all focus-within:bg-background focus-within:shadow-[0_0_0_2px_rgb(var(--primary))]"
          >
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              rows={1}
              maxLength={MESSAGE_MAX_LENGTH}
              placeholder={
                documentId
                  ? "Ask a question about this document…"
                  : "Ask a question across all of your documents…"
              }
              className="max-h-40 w-full resize-none bg-transparent px-2 pt-1 text-base text-foreground outline-none placeholder:text-muted"
            />
            <div className="flex items-center justify-between px-1 pt-1">
              <span className="hidden text-xs text-muted sm:inline">
                Shift + Enter for a new line
              </span>
              <div className="ml-auto flex items-center gap-2">
                {draft.length > MESSAGE_LENGTH_WARNING_THRESHOLD && (
                  <span
                    className={`text-xs font-medium ${
                      draft.length >= MESSAGE_MAX_LENGTH ? "text-danger" : "text-muted"
                    }`}
                  >
                    {draft.length}/{MESSAGE_MAX_LENGTH}
                  </span>
                )}
                {isStreaming ? (
                  <button
                    type="button"
                    onClick={handleStop}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg bg-surface px-3.5 py-2 text-sm font-medium text-foreground shadow-card transition-colors hover:bg-background"
                  >
                    <span className="material-symbols-outlined text-[16px] text-danger">
                      stop_circle
                    </span>
                    <span>Stop</span>
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={draft.trim().length === 0}
                    className="flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-card transition-all hover:scale-[1.02] hover:bg-primary-hover active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:scale-100"
                  >
                    <span>Send</span>
                    <span className="material-symbols-outlined text-[16px]">
                      arrow_upward
                    </span>
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
      </div>

      {/* overflow-hidden matters here, not just for aesthetics: without it,
          this grid item's automatic minimum size is content-based, so a
          long citation list stretches the shared grid ROW (and with it, the
          chat column's composer) far past the viewport - CitationPanel's own
          internal overflow-y-auto list is what should absorb extra content,
          not this column's height. */}
      <div className="hidden overflow-hidden lg:col-span-4 lg:block">
        <CitationPanel citations={activeCitations} />
      </div>
    </div>
  );
}
