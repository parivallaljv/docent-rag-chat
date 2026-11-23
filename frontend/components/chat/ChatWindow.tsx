"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { toast } from "sonner";
import {
  createChat,
  deleteChat,
  getChatMessages,
  getDocuments,
  getSuggestions,
  listChats,
} from "@/lib/api";
import { prewarmChatSocket, respondToProposal, sendChatMessage } from "@/lib/ws";
import {
  getSpeechRecognitionCtor,
  useSpeechRecognitionSupported,
  type SpeechRecognitionLike,
} from "@/lib/speech";
import type {
  ChatCitation,
  ChatHistoryTurn,
  ChatSummary,
  CritiqueClaim,
  DocumentRecord,
  MemoryProposal,
  ProposalDecision,
  ProposalStatus,
} from "@/lib/types";
import MessageStream from "./MessageStream";
import CitationPanel from "./CitationPanel";
import ChatList from "./ChatList";

export type MessageStatus =
  | "connecting"
  | "waking"
  | "streaming"
  | "done"
  | "error";

/** A memory note the assistant proposed, plus where the user's answer to it
 * stands: "pending" (awaiting a click), "sending" (answered, waiting on the
 * server) or the server's final result. */
export interface MessageProposal extends Pick<MemoryProposal, "id" | "text"> {
  status: "pending" | "sending" | ProposalStatus;
}

export interface ChatMessageState {
  id: string;
  role: "user" | "assistant";
  content: string;
  status?: MessageStatus;
  citations?: ChatCitation[];
  /** Server-side id, once known (used for feedback). */
  messageId?: string;
  critique?: CritiqueClaim[];
  proposal?: MessageProposal;
  warning?: string;
  errorMessage?: string;
  /** Set for a connection/auth/quota-level failure (as opposed to a
   * backend-authored `error`/`no_context` message, which needs no special
   * framing beyond the message text itself). */
  errorKind?: "auth" | "quota_exceeded" | "connection";
}

interface ChatWindowProps {
  /** Restrict retrieval to a single document, or null to search across all. */
  documentId: string | null;
  /** Conversation to load on mount (from the `?chat=` query param). */
  initialChatId?: string | null;
}

const MESSAGE_MAX_LENGTH = 4000;
const MESSAGE_LENGTH_WARNING_THRESHOLD = 3500;

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function ChatWindow({ documentId, initialChatId = null }: ChatWindowProps) {
  const [messages, setMessages] = useState<ChatMessageState[]>([]);
  const [draft, setDraft] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [activeCitations, setActiveCitations] = useState<ChatCitation[] | null>(
    null
  );
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);

  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [chatId, setChatId] = useState<string | null>(null);
  const [isLoadingChat, setIsLoadingChat] = useState(false);

  const stopHandleRef = useRef<{ stop: () => void } | null>(null);

  const [suggestions, setSuggestions] = useState<string[]>([]);
  // Bumped on every new turn / chat switch so a slow suggestions response
  // for an older turn can't resurface.
  const suggestionsRunRef = useRef(0);

  const speechSupported = useSpeechRecognitionSupported();
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

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
      recognitionRef.current?.abort();
    };
  }, []);

  function toggleListening() {
    if (recognitionRef.current) {
      recognitionRef.current.stop();
      return;
    }
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) return;
    const recognition = new Ctor();
    recognition.lang = typeof navigator !== "undefined" ? navigator.language || "en-US" : "en-US";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) transcript += event.results[i][0].transcript;
      }
      transcript = transcript.trim();
      if (transcript) {
        setDraft((prev) =>
          `${prev}${prev && !/\s$/.test(prev) ? " " : ""}${transcript}`.slice(0, MESSAGE_MAX_LENGTH)
        );
      }
    };
    recognition.onerror = (event) => {
      if (event.error && event.error !== "no-speech" && event.error !== "aborted") {
        toast.error(
          event.error === "not-allowed"
            ? "Microphone access was blocked."
            : "Voice input isn't working right now."
        );
      }
    };
    recognition.onend = () => {
      recognitionRef.current = null;
      setIsListening(false);
    };
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setIsListening(true);
    } catch {
      recognitionRef.current = null;
    }
  }

  function refreshChats() {
    listChats()
      .then(setChats)
      .catch(() => {
        // Non-fatal: the conversation list just stays as it was.
      });
  }

  function syncUrl(id: string | null) {
    const params = new URLSearchParams();
    if (documentId) params.set("documentId", documentId);
    if (id) params.set("chat", id);
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/chat?${qs}` : "/chat");
  }

  async function loadChat(id: string) {
    setIsLoadingChat(true);
    try {
      const stored = await getChatMessages(id);
      setMessages(
        stored.map((m) => ({
          id: m.id,
          role: m.role,
          content: m.content,
          status: m.role === "assistant" ? "done" : undefined,
          citations: m.citations ?? undefined,
          messageId: m.role === "assistant" ? m.id : undefined,
        }))
      );
      suggestionsRunRef.current += 1;
      setSuggestions([]);
      const lastWithCitations = [...stored].reverse().find((m) => m.citations?.length);
      setActiveCitations(lastWithCitations?.citations ?? null);
      setChatId(id);
      syncUrl(id);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't load that conversation.");
      if (id === initialChatId) syncUrl(null);
    } finally {
      setIsLoadingChat(false);
    }
  }

  function handleNewChat() {
    if (isStreaming) return;
    setChatId(null);
    setMessages([]);
    setActiveCitations(null);
    suggestionsRunRef.current += 1;
    setSuggestions([]);
    syncUrl(null);
  }

  async function handleDeleteChat(id: string) {
    try {
      await deleteChat(id);
      setChats((prev) => prev.filter((chat) => chat.id !== id));
      if (id === chatId) handleNewChat();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Couldn't delete the conversation.");
    }
  }

  useEffect(() => {
    listChats()
      .then(setChats)
      .catch(() => {});
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (initialChatId) void loadChat(initialChatId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function handleProposalDecision(message: ChatMessageState, decision: ProposalDecision) {
    const proposal = message.proposal;
    if (!proposal || proposal.status !== "pending") return;
    updateMessage(message.id, (m) =>
      m.proposal ? { ...m, proposal: { ...m.proposal, status: "sending" } } : m
    );
    respondToProposal(proposal.id, decision, (status) => {
      updateMessage(message.id, (m) =>
        m.proposal?.id === proposal.id ? { ...m, proposal: { ...m.proposal, status } } : m
      );
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(draft.trim());
  }

  async function sendQuestion(text: string) {
    if (!text || isStreaming || isLoadingChat) return;
    recognitionRef.current?.stop();
    suggestionsRunRef.current += 1;
    const run = suggestionsRunRef.current;
    setSuggestions([]);
    let turnFailed = false;

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

    // Lazily create the conversation on the first message. If that fails,
    // fall back to a stateless turn that still sends client-side history.
    let activeChatId = chatId;
    if (!activeChatId) {
      try {
        const created = await createChat();
        activeChatId = created.id;
        setChatId(created.id);
        syncUrl(created.id);
      } catch (err) {
        toast.error(
          err instanceof Error ? err.message : "Couldn't save this conversation."
        );
      }
    }

    stopHandleRef.current = sendChatMessage(
      activeChatId
        ? { message: text, documentId, chatId: activeChatId }
        : { message: text, documentId, history },
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
        onCritique: (claims) => {
          updateMessage(assistantId, (m) => ({ ...m, critique: claims }));
        },
        onProposal: (proposal) => {
          updateMessage(assistantId, (m) => ({
            ...m,
            proposal: { id: proposal.id, text: proposal.text, status: "pending" },
          }));
        },
        onCitations: (citations, meta) => {
          updateMessage(assistantId, (m) => ({
            ...m,
            status: "done",
            citations,
            messageId: meta?.messageId ?? m.messageId,
            warning: meta?.warning,
          }));
          setActiveCitations(citations);
        },
        onError: (message, kind) => {
          turnFailed = true;
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
          refreshChats();
          if (activeChatId && !turnFailed) {
            const forChat = activeChatId;
            getSuggestions(forChat)
              .then((items) => {
                if (suggestionsRunRef.current === run) setSuggestions(items);
              })
              .catch(() => {
                // Suggestions are optional; ignore failures silently.
              });
          }
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

        <ChatList
          chats={chats}
          activeId={chatId}
          disabled={isStreaming || isLoadingChat}
          onSelect={(id) => void loadChat(id)}
          onNew={handleNewChat}
          onDelete={(id) => void handleDeleteChat(id)}
        />

        <MessageStream
          messages={messages}
          onShowCitations={handleShowCitations}
          onProposalDecision={handleProposalDecision}
        />

        {suggestions.length > 0 && !isStreaming && (
          <div className="flex flex-wrap gap-2 px-4 pb-1">
            {suggestions.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => void sendQuestion(suggestion)}
                className="rounded-full bg-surface-muted px-3 py-1.5 text-left text-xs font-medium text-foreground transition-colors hover:bg-primary/10 hover:text-primary"
              >
                {suggestion}
              </button>
            ))}
          </div>
        )}

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
                {speechSupported && !isStreaming && (
                  <button
                    type="button"
                    onClick={toggleListening}
                    aria-label={isListening ? "Stop voice input" : "Start voice input"}
                    aria-pressed={isListening}
                    title={isListening ? "Stop voice input" : "Voice input"}
                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg transition-colors ${
                      isListening
                        ? "animate-pulse bg-danger/10 text-danger"
                        : "text-muted hover:bg-surface hover:text-foreground"
                    }`}
                  >
                    <span className="material-symbols-outlined text-[20px]">
                      {isListening ? "mic" : "mic_none"}
                    </span>
                  </button>
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
