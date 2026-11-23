import { describe, expect, it, vi } from "vitest";
import { dispatchTurnEvent, parseServerEvent, type TurnEvent } from "./wsEvents";

describe("parseServerEvent", () => {
  it("ignores non-objects, unknown types and turn events without a turn_id", () => {
    expect(parseServerEvent(null)).toBeNull();
    expect(parseServerEvent("token")).toBeNull();
    expect(parseServerEvent({ type: "something_new", turn_id: "t" })).toBeNull();
    expect(parseServerEvent({ type: "token", content: "x" })).toBeNull();
    expect(parseServerEvent({ type: "token", turn_id: "t" })).toBeNull();
  });

  it("parses token, stopped and turn_end", () => {
    expect(parseServerEvent({ type: "token", turn_id: "t", content: "hi" })).toEqual({
      type: "token",
      turnId: "t",
      content: "hi",
    });
    expect(parseServerEvent({ type: "stopped", turn_id: "t" })).toEqual({
      type: "stopped",
      turnId: "t",
    });
    expect(parseServerEvent({ type: "turn_end", turn_id: "t" })).toEqual({
      type: "turn_end",
      turnId: "t",
    });
  });

  it("parses citations with metadata and tolerates missing fields", () => {
    expect(
      parseServerEvent({
        type: "citations",
        turn_id: "t",
        citations: [{ id: "c" }],
        message_id: "m1",
        warning: "possible_prompt_leak",
      })
    ).toEqual({
      type: "citations",
      turnId: "t",
      citations: [{ id: "c" }],
      meta: { messageId: "m1", warning: "possible_prompt_leak" },
    });
    expect(parseServerEvent({ type: "citations", turn_id: "t" })).toEqual({
      type: "citations",
      turnId: "t",
      citations: [],
      meta: { messageId: undefined, warning: undefined },
    });
  });

  it("normalises critique claims and drops the event when none are valid", () => {
    expect(
      parseServerEvent({
        type: "critique",
        turn_id: "t",
        claims: [{ claim: "a", supported: true, excerpt: 2 }, { claim: "b" }, null, { nope: 1 }],
      })
    ).toEqual({
      type: "critique",
      turnId: "t",
      claims: [
        { claim: "a", supported: true, excerpt: 2 },
        { claim: "b", supported: false, excerpt: null },
      ],
    });
    expect(parseServerEvent({ type: "critique", turn_id: "t", claims: [{}] })).toBeNull();
    expect(parseServerEvent({ type: "critique", turn_id: "t" })).toBeNull();
  });

  it("maps error, no_context and quota_exceeded with default messages", () => {
    expect(parseServerEvent({ type: "error", turn_id: "t", message: "boom" })).toEqual({
      type: "error",
      turnId: "t",
      message: "boom",
      quota: false,
    });
    expect(parseServerEvent({ type: "no_context", turn_id: "t" })).toMatchObject({
      type: "error",
      message: "Something went wrong.",
      quota: false,
    });
    expect(parseServerEvent({ type: "quota_exceeded", turn_id: "t" })).toMatchObject({
      type: "error",
      message: "Daily AI budget exhausted.",
      quota: true,
    });
  });

  it("parses a memory proposal and rejects malformed ones", () => {
    expect(
      parseServerEvent({
        type: "proposal",
        turn_id: "t",
        id: "p1",
        action: "save_memory_note",
        text: "Prefers metric units",
      })
    ).toEqual({
      type: "proposal",
      turnId: "t",
      proposal: { id: "p1", action: "save_memory_note", text: "Prefers metric units" },
    });
    const base = { type: "proposal", turn_id: "t", id: "p1", action: "save_memory_note", text: "x" };
    expect(parseServerEvent({ ...base, action: "delete_everything" })).toBeNull();
    expect(parseServerEvent({ ...base, id: 5 })).toBeNull();
    expect(parseServerEvent({ ...base, text: "   " })).toBeNull();
    expect(parseServerEvent({ ...base, turn_id: undefined })).toBeNull();
  });

  it("parses proposal_result without a turn_id and rejects unknown statuses", () => {
    for (const status of ["saved", "rejected", "expired", "failed"] as const) {
      expect(
        parseServerEvent({ type: "proposal_result", proposal_id: "p1", status })
      ).toEqual({ type: "proposal_result", proposalId: "p1", status });
    }
    expect(
      parseServerEvent({ type: "proposal_result", proposal_id: "p1", status: "maybe" })
    ).toBeNull();
    expect(parseServerEvent({ type: "proposal_result", status: "saved" })).toBeNull();
  });
});

describe("dispatchTurnEvent", () => {
  function handlers() {
    return {
      onToken: vi.fn(),
      onCitations: vi.fn(),
      onCritique: vi.fn(),
      onProposal: vi.fn(),
      onError: vi.fn(),
      onStopped: vi.fn(),
    };
  }

  it("routes each event to its callback", () => {
    const h = handlers();
    const proposal = { id: "p1", action: "save_memory_note" as const, text: "x" };
    const events: TurnEvent[] = [
      { type: "token", turnId: "t", content: "hi" },
      { type: "citations", turnId: "t", citations: [], meta: { messageId: "m" } },
      { type: "critique", turnId: "t", claims: [] },
      { type: "proposal", turnId: "t", proposal },
      { type: "error", turnId: "t", message: "boom", quota: false },
      { type: "error", turnId: "t", message: "budget", quota: true },
      { type: "stopped", turnId: "t" },
    ];
    events.forEach((e) => dispatchTurnEvent(e, h));

    expect(h.onToken).toHaveBeenCalledWith("hi");
    expect(h.onCitations).toHaveBeenCalledWith([], { messageId: "m" });
    expect(h.onCritique).toHaveBeenCalledWith([]);
    expect(h.onProposal).toHaveBeenCalledWith(proposal);
    expect(h.onError).toHaveBeenNthCalledWith(1, "boom");
    expect(h.onError).toHaveBeenNthCalledWith(2, "budget", "quota_exceeded");
    expect(h.onStopped).toHaveBeenCalledTimes(1);
  });

  it("does not throw when optional callbacks are absent and ignores turn_end", () => {
    const onToken = vi.fn();
    const base = { onToken, onCitations: vi.fn(), onError: vi.fn() };
    expect(() => {
      dispatchTurnEvent({ type: "proposal", turnId: "t", proposal: { id: "p", action: "save_memory_note", text: "x" } }, base);
      dispatchTurnEvent({ type: "critique", turnId: "t", claims: [] }, base);
      dispatchTurnEvent({ type: "stopped", turnId: "t" }, base);
      dispatchTurnEvent({ type: "turn_end", turnId: "t" }, base);
    }).not.toThrow();
    expect(onToken).not.toHaveBeenCalled();
  });
});
