"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { buildAnswerMarkdown, downloadMarkdown } from "@/lib/exportMarkdown";
import type { ChatMessageState } from "./ChatWindow";
import MessageActions, { FactCheck, MemoryProposalCard } from "./MessageActions";
import type { ProposalDecision } from "@/lib/types";

// Assistant responses come back as markdown (Gemini/Groq both format
// structured answers with headers, bold, and bullet lists) - render it as
// real HTML rather than literal "**"/"#"/"*" characters, styled to match
// the app's existing typography rather than default browser/prose styles.
// User messages are never markdown-formatted, so they stay plain text (see
// MessageBubble below) - no reason to parse arbitrary user input as markdown.
const markdownComponents: Components = {
  p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => (
    <h3 className="mb-1.5 mt-3 font-heading text-base font-semibold first:mt-0">{children}</h3>
  ),
  h2: ({ children }) => (
    <h3 className="mb-1.5 mt-3 font-heading text-base font-semibold first:mt-0">{children}</h3>
  ),
  h3: ({ children }) => (
    <h4 className="mb-1 mt-2.5 font-heading text-sm font-semibold first:mt-0">{children}</h4>
  ),
  ul: ({ children }) => <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>,
  ol: ({ children }) => <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>,
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-primary underline hover:no-underline"
    >
      {children}
    </a>
  ),
  code: ({ children }) => (
    <code className="rounded bg-background/60 px-1 py-0.5 font-mono text-[13px]">
      {children}
    </code>
  ),
  pre: ({ children }) => (
    <pre className="mb-2 overflow-x-auto rounded-lg bg-background/60 p-2 font-mono text-[13px] last:mb-0">
      {children}
    </pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border pl-3 text-muted">{children}</blockquote>
  ),
  // GFM tables (via remark-gfm) had no styling at all before this - browser
  // table defaults have no row separation, which is what made rows hard to
  // tell apart. Row dividers + a subtle zebra stripe fix that; the
  // overflow-x-auto wrapper keeps a wide table from blowing out the bubble's
  // max-width instead of wrapping awkwardly.
  table: ({ children }) => (
    <div className="mb-2 overflow-x-auto rounded-lg border border-border last:mb-0">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="bg-surface-muted">{children}</thead>,
  // A row's own border is ignored under border-collapse (the table has it)
  // -- browsers only respect borders set on the actual cells, which merge
  // into one shared line between adjacent rows. The zebra stripe (a
  // background, unaffected by border-collapse) works fine directly on tr.
  tr: ({ children }) => <tr className="even:bg-surface-muted/40">{children}</tr>,
  th: ({ children }) => (
    <th className="whitespace-nowrap border-b border-border px-3 py-2 text-left font-heading text-xs font-semibold uppercase tracking-wide text-muted">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border px-3 py-2 align-top">{children}</td>
  ),
};

interface MessageStreamProps {
  messages: ChatMessageState[];
  onShowCitations: (message: ChatMessageState) => void;
  onProposalDecision: (message: ChatMessageState, decision: ProposalDecision) => void;
}

// How close to the bottom (in px) still counts as "pinned" -- the user
// hasn't deliberately scrolled away to read earlier history.
const NEAR_BOTTOM_THRESHOLD_PX = 80;

export default function MessageStream({
  messages,
  onShowCitations,
  onProposalDecision,
}: MessageStreamProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);
  // Whether the view should auto-follow new content. Starts pinned (a fresh
  // chat opens at the bottom); a ref, not state, since updating it on every
  // scroll event must not itself trigger a re-render.
  const isPinnedRef = useRef(true);
  const prevLengthRef = useRef(messages.length);

  useEffect(() => {
    // A brand-new message (the user sent one, or a new assistant placeholder
    // appeared) always re-pins to the bottom, matching standard chat-app
    // behavior -- but an in-place update to an EXISTING message (streamed
    // tokens appending to the last assistant bubble, citations attaching)
    // must not fight a manual scroll-up with the same force. Previously this
    // effect scrolled unconditionally on every `messages` change, which
    // fires on every single streamed token and made it impossible to read
    // earlier history mid-response.
    const isNewMessage = messages.length !== prevLengthRef.current;
    prevLengthRef.current = messages.length;
    if (isNewMessage) {
      isPinnedRef.current = true;
    }
    if (isPinnedRef.current) {
      bottomRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages]);

  function handleScroll(event: React.UIEvent<HTMLDivElement>) {
    const el = event.currentTarget;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    isPinnedRef.current = distanceFromBottom < NEAR_BOTTOM_THRESHOLD_PX;
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
        <p className="text-base font-medium text-foreground">
          Ask your first question
        </p>
        <p className="mt-1 max-w-sm text-sm text-muted">
          Answers stream in as they&apos;re generated, with citations linking
          back to the exact page they came from.
        </p>
      </div>
    );
  }

  return (
    <div
      className="flex-1 space-y-4 overflow-y-auto scrollbar-thin px-4 py-4"
      onScroll={handleScroll}
    >
      <AnimatePresence initial={false}>
        {messages.map((message, index) => (
          <MessageBubble
            key={message.id}
            message={message}
            question={
              [...messages.slice(0, index)].reverse().find((m) => m.role === "user")
                ?.content ?? null
            }
            onShowCitations={onShowCitations}
            onProposalDecision={onProposalDecision}
          />
        ))}
      </AnimatePresence>
      <div ref={bottomRef} />
    </div>
  );
}

function MessageBubble({
  message,
  question,
  onShowCitations,
  onProposalDecision,
}: {
  message: ChatMessageState;
  question: string | null;
  onShowCitations: (message: ChatMessageState) => void;
  onProposalDecision: (message: ChatMessageState, decision: ProposalDecision) => void;
}) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className={`flex items-start gap-3 ${isUser ? "justify-end" : "justify-start"}`}
    >
      {!isUser && (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary shadow-card">
          <span className="material-symbols-outlined text-[18px]">neurology</span>
        </div>
      )}
      <div
        className={`max-w-[85%] rounded-2xl px-5 py-3 text-base leading-relaxed shadow-card ${
          isUser
            ? "rounded-tr-sm bg-primary text-primary-foreground"
            : "rounded-tl-sm bg-surface-muted text-foreground"
        }`}
      >
        {!isUser && message.warning === "possible_prompt_leak" && (
          <div className="mb-2 flex items-start gap-1.5 rounded-lg bg-warning/10 px-2.5 py-1.5 text-xs text-warning">
            <span className="material-symbols-outlined mt-px text-[14px]">shield</span>
            <span>
              This answer may reveal internal instructions. Treat it with caution.
            </span>
          </div>
        )}

        {!isUser && message.status === "waking" && (
          <WakingIndicator />
        )}

        {!isUser && message.status === "connecting" && (
          <TypingIndicator />
        )}

        {message.content &&
          (isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {message.content}
            </ReactMarkdown>
          ))}

        {!isUser && message.status === "done" && !message.content && (
          <p className="text-sm italic text-muted">Stopped - no response was generated.</p>
        )}

        {!isUser && message.status === "streaming" && message.content && (
          <span
            aria-hidden
            className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-current align-middle"
          />
        )}

        {!isUser && message.status === "error" && (
          <div className="mt-1 flex items-start gap-2">
            <span className="material-symbols-outlined mt-0.5 text-[16px] text-danger">
              error
            </span>
            <div>
              <p className="text-sm font-medium text-danger">
                {message.errorMessage ?? "Something went wrong generating a response."}
              </p>
              {message.errorKind === "auth" && (
                <Link
                  href="/login"
                  className="mt-1.5 inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                >
                  Sign in again
                </Link>
              )}
            </div>
          </div>
        )}

        {!isUser &&
          message.status === "done" &&
          message.citations &&
          message.citations.length > 0 && (
            <button
              type="button"
              onClick={() => onShowCitations(message)}
              className="mt-2.5 inline-flex items-center gap-2 rounded-lg bg-surface px-3 py-1.5 text-xs font-medium text-foreground shadow-card transition-colors hover:bg-background"
            >
              <span className="material-symbols-outlined text-[16px] text-primary">
                article
              </span>
              <span>
                View {message.citations.length}{" "}
                {message.citations.length === 1 ? "source" : "sources"}
              </span>
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
                {message.citations.length}
              </span>
            </button>
          )}

        {!isUser && message.status === "done" && message.critique && (
          <FactCheck claims={message.critique} />
        )}

        {!isUser && message.status === "done" && message.proposal && (
          <MemoryProposalCard
            proposal={message.proposal}
            onDecide={(decision) => onProposalDecision(message, decision)}
          />
        )}

        {!isUser && message.status === "done" && message.content && (
          <MessageActions
            content={message.content}
            messageId={message.messageId}
            onExport={() =>
              downloadMarkdown(
                "answer.md",
                buildAnswerMarkdown(question, message.content, message.citations)
              )
            }
          />
        )}
      </div>
    </motion.div>
  );
}

function TypingIndicator() {
  return (
    <span className="flex items-center gap-1 py-0.5" aria-label="Thinking">
      <Dot delay="0ms" />
      <Dot delay="120ms" />
      <Dot delay="240ms" />
    </span>
  );
}

function WakingIndicator() {
  return (
    <div className="flex items-center gap-2 py-0.5 text-muted">
      <span className="flex items-center gap-1">
        <Dot delay="0ms" />
        <Dot delay="120ms" />
        <Dot delay="240ms" />
      </span>
      <span className="text-xs font-medium">
        Waking up the server… this can take up to a minute on the free tier.
      </span>
    </div>
  );
}

function Dot({ delay }: { delay: string }) {
  return (
    <span
      className="h-1.5 w-1.5 animate-bounce rounded-full bg-current"
      style={{ animationDelay: delay }}
    />
  );
}
