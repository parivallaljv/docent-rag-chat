import { getSupabaseBrowserClient } from "./supabaseClient";
import { API_URL } from "./api";
import type { ChatCitation, ChatHistoryTurn } from "./types";

/**
 * Persistent WebSocket client for /chat/ws, replacing the old one-fetch-
 * per-turn SSE approach (lib/sse.ts, now removed). One connection is shared
 * across every chat turn for the lifetime of the page, rather than opening
 * a new HTTP request per question.
 *
 * Auth handshake: the browser's native WebSocket API can't set a custom
 * `Authorization` header on the handshake request, and a `?token=` query
 * param would land in server access logs/browser history - so the first
 * message sent after the socket opens is `{"type":"auth","token":"..."}`,
 * and everything else waits for `{"type":"auth_ok"}` before being sent.
 *
 * Message protocol (mirrors backend/app/routers/chat.py's docstring):
 *   -> {"type":"auth","token":"..."}
 *   -> {"type":"message","turn_id":"...","message":"...","document_id":...,"history":[...]}
 *   -> {"type":"stop","turn_id":"..."}
 *   <- {"type":"auth_ok"} | {"type":"auth_error","message":"..."}
 *   <- {"type":"token"|"citations"|"no_context"|"error"|"quota_exceeded"|"stopped"|"turn_end", "turn_id":"...", ...}
 */

export interface ChatStreamRequest {
  message: string;
  documentId?: string | null;
  history?: ChatHistoryTurn[];
}

export interface ChatSocketCallbacks {
  /** Fires if the connection isn't ready within ~2s of sending - a strong
   * signal the Render free-tier backend is cold-starting. */
  onWaking?: () => void;
  /** Fires once the turn's message has actually been sent (connection ready). */
  onOpen?: () => void;
  /** Fires once per streamed token/text chunk, in order. */
  onToken: (token: string) => void;
  /** Fires once, with the final citations list, on a successful turn. */
  onCitations: (citations: ChatCitation[]) => void;
  /**
   * Fires on any error for this turn. `kind` distinguishes how to frame it:
   *  - "auth": the session was rejected/expired during the WS handshake.
   *  - "quota_exceeded": the demo's daily AI budget is used up.
   *  - "connection": the socket never became ready / dropped before a
   *    response came back (no backend-authored message to show).
   *  - undefined: a backend-authored message (SSE-equivalent `error` or
   *    `no_context`) - already good, specific copy, render as-is.
   */
  onError: (message: string, kind?: "auth" | "quota_exceeded" | "connection") => void;
  /** Fires when a `stop()` call is actually acknowledged by the backend
   * (generation was cancelled server-side). Without this, the assistant
   * bubble is left showing whatever transient status it had when stop was
   * clicked, since onTurnEnd alone only resets the composer's isStreaming
   * flag, not the message's own displayed state. */
  onStopped?: () => void;
  /** Always fires exactly once per turn, success or failure - the signal to
   * stop showing a "streaming" state for this message. */
  onTurnEnd: () => void;
}

type ConnectionStatus = "connecting" | "ready" | "closed";

interface PendingTurn {
  callbacks: ChatSocketCallbacks;
  ended: boolean;
}

const WAKE_THRESHOLD_MS = 2000;
const MAX_RECONNECT_DELAY_MS = 30000;

class ChatSocket {
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = "closed";
  private pendingTurns = new Map<string, PendingTurn>();
  private sendQueue: Array<() => void> = [];
  private reconnectAttempt = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private connectPromise: Promise<void> | null = null;

  /** Resolves once the socket is authenticated and ready to send, opening a
   * new connection first if none is in progress. */
  async ensureReady(): Promise<void> {
    if (this.status === "ready") return;
    if (this.connectPromise) return this.connectPromise;
    this.connectPromise = this._connect();
    try {
      await this.connectPromise;
    } finally {
      this.connectPromise = null;
    }
  }

  private async _connect(): Promise<void> {
    const supabase = getSupabaseBrowserClient();
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) {
      this._failAllPending("You must be signed in to chat.", "auth");
      throw new Error("no session");
    }

    this.status = "connecting";
    const wsUrl = API_URL.replace(/^http/, "ws") + "/chat/ws";

    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      this.ws = ws;
      let settled = false;

      ws.onopen = () => {
        ws.send(JSON.stringify({ type: "auth", token }));
      };

      ws.onmessage = (event) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }

        if (data.type === "auth_ok") {
          this.status = "ready";
          this.reconnectAttempt = 0;
          settled = true;
          this._flushQueue();
          resolve();
          return;
        }
        if (data.type === "auth_error") {
          settled = true;
          this._failAllPending(
            typeof data.message === "string" ? data.message : "Authentication failed.",
            "auth"
          );
          reject(new Error("auth rejected"));
          ws.close();
          return;
        }

        this._routeMessage(data);
      };

      ws.onclose = () => {
        this.ws = null;
        this.status = "closed";
        if (!settled) {
          settled = true;
          reject(new Error("connection closed before auth"));
        }
        this._failAllPending(
          "Can't reach the server. Check your connection and try again.",
          "connection"
        );
        this._scheduleReconnect();
      };

      ws.onerror = () => {
        // onclose always follows onerror for a WebSocket; no separate
        // handling needed here.
      };
    });
  }

  private _scheduleReconnect() {
    if (this.reconnectTimer) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, MAX_RECONNECT_DELAY_MS);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      // Reconnect lazily on the next actual send, not proactively - there's
      // no point holding a connection open with nothing to send.
    }, delay);
  }

  private _routeMessage(data: Record<string, unknown>) {
    const turnId = typeof data.turn_id === "string" ? data.turn_id : undefined;
    if (!turnId) return;
    const turn = this.pendingTurns.get(turnId);
    if (!turn) return;

    switch (data.type) {
      case "token":
        if (typeof data.content === "string") turn.callbacks.onToken(data.content);
        break;
      case "citations":
        turn.callbacks.onCitations(Array.isArray(data.citations) ? (data.citations as ChatCitation[]) : []);
        break;
      case "no_context":
      case "error":
        turn.callbacks.onError(typeof data.message === "string" ? data.message : "Something went wrong.");
        break;
      case "quota_exceeded":
        turn.callbacks.onError(
          typeof data.message === "string" ? data.message : "Daily AI budget exhausted.",
          "quota_exceeded"
        );
        break;
      case "stopped":
        turn.callbacks.onStopped?.();
        break;
      case "turn_end":
        if (!turn.ended) {
          turn.ended = true;
          turn.callbacks.onTurnEnd();
        }
        this.pendingTurns.delete(turnId);
        break;
    }
  }

  private _flushQueue() {
    const queue = this.sendQueue;
    this.sendQueue = [];
    queue.forEach((send) => send());
  }

  private _failAllPending(message: string, kind: "auth" | "connection") {
    const turns = Array.from(this.pendingTurns.values());
    this.pendingTurns.clear();
    for (const turn of turns) {
      if (!turn.ended) {
        turn.ended = true;
        turn.callbacks.onError(message, kind);
        turn.callbacks.onTurnEnd();
      }
    }
    const queued = this.sendQueue;
    this.sendQueue = [];
    void queued; // queued sends are simply dropped; their turns were already failed above
  }

  send(turnId: string, request: ChatStreamRequest, callbacks: ChatSocketCallbacks): void {
    this.pendingTurns.set(turnId, { callbacks, ended: false });

    const doSend = () => {
      if (this.status !== "ready" || !this.ws) return;
      callbacks.onOpen?.();
      this.ws.send(
        JSON.stringify({
          type: "message",
          turn_id: turnId,
          message: request.message,
          document_id: request.documentId ?? null,
          history: request.history ?? [],
        })
      );
    };

    const wakeTimer = setTimeout(() => {
      if (this.status !== "ready") callbacks.onWaking?.();
    }, WAKE_THRESHOLD_MS);

    this.ensureReady()
      .then(() => {
        clearTimeout(wakeTimer);
        doSend();
      })
      .catch(() => {
        clearTimeout(wakeTimer);
        // ensureReady() already routed a failure to every pending turn
        // (including this one) via _failAllPending.
      });
  }

  stop(turnId: string): void {
    if (this.status === "ready" && this.ws) {
      this.ws.send(JSON.stringify({ type: "stop", turn_id: turnId }));
      // Don't resolve the turn locally here - wait for the server's real
      // "stopped" + "turn_end" frames (routed by _routeMessage) so the UI
      // reflects actual cancellation, not just that a stop request was
      // sent. Resolving eagerly would also delete the turn from
      // pendingTurns before those frames arrive, so _routeMessage would
      // find nothing to route them to.
      return;
    }
    // Not connected - nothing to cancel server-side, and no server frames
    // will ever arrive for this turn, so resolve it locally instead of
    // leaving the UI stuck waiting forever.
    const turn = this.pendingTurns.get(turnId);
    if (turn && !turn.ended) {
      turn.ended = true;
      turn.callbacks.onTurnEnd();
    }
    this.pendingTurns.delete(turnId);
  }
}

let sharedSocket: ChatSocket | null = null;

function getChatSocket(): ChatSocket {
  if (!sharedSocket) sharedSocket = new ChatSocket();
  return sharedSocket;
}

/** Opens (or reuses) the shared connection ahead of time, so it's likely
 * already authenticated by the time the user actually sends a message -
 * called once on the chat page's mount. Errors are swallowed here; a real
 * send will surface them properly via onError/onTurnEnd. */
export function prewarmChatSocket(): void {
  getChatSocket()
    .ensureReady()
    .catch(() => {
      /* a real send will retry and report the error */
    });
}

let turnCounter = 0;
function createTurnId(): string {
  turnCounter += 1;
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `turn-${Date.now()}-${turnCounter}`;
}

/** Sends one chat turn over the shared WebSocket connection (connecting/
 * authenticating first if needed). Returns a handle to cancel it. */
export function sendChatMessage(
  request: ChatStreamRequest,
  callbacks: ChatSocketCallbacks
): { stop: () => void } {
  const turnId = createTurnId();
  const socket = getChatSocket();
  socket.send(turnId, request, callbacks);
  return { stop: () => socket.stop(turnId) };
}
