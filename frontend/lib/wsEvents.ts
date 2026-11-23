import type { ChatSocketCallbacks } from "./ws";
import type {
  ChatCitation,
  CitationsMeta,
  CritiqueClaim,
  MemoryProposal,
  ProposalStatus,
} from "./types";

/**
 * Pure parsing/dispatch for server frames on the chat WebSocket, kept free of
 * any browser/Supabase imports so it can be unit tested in isolation.
 */

const PROPOSAL_STATUSES: readonly ProposalStatus[] = ["saved", "rejected", "expired", "failed"];

/** A turn-scoped frame (carries a turn_id), validated and normalised. */
export type TurnEvent =
  | { type: "token"; turnId: string; content: string }
  | { type: "citations"; turnId: string; citations: ChatCitation[]; meta: CitationsMeta }
  | { type: "critique"; turnId: string; claims: CritiqueClaim[] }
  | { type: "proposal"; turnId: string; proposal: MemoryProposal }
  | { type: "error"; turnId: string; message: string; quota: boolean }
  | { type: "stopped"; turnId: string }
  | { type: "turn_end"; turnId: string };

/** Frames that aren't tied to a turn. */
export type GlobalEvent = {
  type: "proposal_result";
  proposalId: string;
  status: ProposalStatus;
};

export type ServerEvent = TurnEvent | GlobalEvent;

/** Parses one decoded server frame. Returns null for anything unknown or
 * malformed, so new/unexpected server events are ignored safely. */
export function parseServerEvent(data: unknown): ServerEvent | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Record<string, unknown>;

  if (d.type === "proposal_result") {
    if (typeof d.proposal_id !== "string") return null;
    const status = PROPOSAL_STATUSES.find((s) => s === d.status);
    if (!status) return null;
    return { type: "proposal_result", proposalId: d.proposal_id, status };
  }

  const turnId = typeof d.turn_id === "string" ? d.turn_id : undefined;
  if (!turnId) return null;

  switch (d.type) {
    case "token":
      return typeof d.content === "string" ? { type: "token", turnId, content: d.content } : null;
    case "citations":
      return {
        type: "citations",
        turnId,
        citations: Array.isArray(d.citations) ? (d.citations as ChatCitation[]) : [],
        meta: {
          messageId: typeof d.message_id === "string" ? d.message_id : undefined,
          warning: typeof d.warning === "string" ? d.warning : undefined,
        },
      };
    case "critique": {
      if (!Array.isArray(d.claims)) return null;
      const claims = (d.claims as unknown[]).flatMap((raw): CritiqueClaim[] => {
        const c = raw as Partial<CritiqueClaim> | null;
        if (!c || typeof c.claim !== "string") return [];
        return [
          {
            claim: c.claim,
            supported: c.supported === true,
            excerpt: typeof c.excerpt === "number" ? c.excerpt : null,
          },
        ];
      });
      return claims.length > 0 ? { type: "critique", turnId, claims } : null;
    }
    case "proposal": {
      if (
        typeof d.id !== "string" ||
        d.action !== "save_memory_note" ||
        typeof d.text !== "string" ||
        !d.text.trim()
      ) {
        return null;
      }
      return {
        type: "proposal",
        turnId,
        proposal: { id: d.id, action: "save_memory_note", text: d.text },
      };
    }
    case "no_context":
    case "error":
      return {
        type: "error",
        turnId,
        message: typeof d.message === "string" ? d.message : "Something went wrong.",
        quota: false,
      };
    case "quota_exceeded":
      return {
        type: "error",
        turnId,
        message: typeof d.message === "string" ? d.message : "Daily AI budget exhausted.",
        quota: true,
      };
    case "stopped":
      return { type: "stopped", turnId };
    case "turn_end":
      return { type: "turn_end", turnId };
    default:
      return null;
  }
}

/** Calls the matching per-turn callback for a parsed event. `turn_end` is
 * left to the socket, which also owns the pending-turn bookkeeping. */
export function dispatchTurnEvent(
  event: TurnEvent,
  callbacks: Pick<
    ChatSocketCallbacks,
    "onToken" | "onCitations" | "onCritique" | "onProposal" | "onError" | "onStopped"
  >
): void {
  switch (event.type) {
    case "token":
      callbacks.onToken(event.content);
      break;
    case "citations":
      callbacks.onCitations(event.citations, event.meta);
      break;
    case "critique":
      callbacks.onCritique?.(event.claims);
      break;
    case "proposal":
      callbacks.onProposal?.(event.proposal);
      break;
    case "error":
      if (event.quota) callbacks.onError(event.message, "quota_exceeded");
      else callbacks.onError(event.message);
      break;
    case "stopped":
      callbacks.onStopped?.();
      break;
    case "turn_end":
      break;
  }
}
