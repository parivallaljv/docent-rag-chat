import asyncio
import time
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.agent import proposals
from app.agent.loop import run_tool_agent
from app.agent.proposals import ProposalStore, append_note
from app.agent.tools import build_tools
from app.main import app
from app.retrieval import prompt as prompt_mod
from app.retrieval.search import Candidate, merge_neighbors
from app.routers import chat

UID = "11111111-1111-1111-1111-111111111111"


def run(c):
    return asyncio.run(c)


# ---- proposal store ----
def test_store_only_known_action_scoped_and_single_use():
    s = ProposalStore()
    assert s.create("u1", "delete_everything", "x") is None
    assert s.create("u1", proposals.ACTION_SAVE_MEMORY, "   ") is None
    p = s.create("u1", proposals.ACTION_SAVE_MEMORY, "prefers  short   answers")
    assert p.text == "prefers short answers"
    assert s.take("u2", p.id) is None  # another user cannot approve it
    assert s.take("u1", p.id) is p
    assert s.take("u1", p.id) is None  # single use


def test_store_expiry_and_cap():
    s = ProposalStore(ttl=-1)
    p = s.create("u", proposals.ACTION_SAVE_MEMORY, "x")
    assert s.take("u", p.id) is None
    s = ProposalStore()
    ids = [
        s.create("u", proposals.ACTION_SAVE_MEMORY, f"n{i}").id
        for i in range(proposals.MAX_PER_USER + 3)
    ]
    assert sum(1 for i in ids if s.take("u", i)) == proposals.MAX_PER_USER


def test_append_note_respects_limit():
    assert append_note(None, "a") == "- a"
    assert append_note("- a", "b") == "- a\n- b"
    big = "\n".join(f"- {'x' * 100}{i}" for i in range(30))
    out = append_note(big, "new")
    assert len(out) <= proposals.MEMORY_LIMIT and out.endswith("- new")


# ---- tool + loop ----
def test_propose_tool_only_when_allowed_and_collects():
    assert "propose_memory_note" not in build_tools(None, "u", None)
    tools = build_tools(None, "u", None, allow_proposals=True)
    res = run(tools["propose_memory_note"].run({"note": "  likes   tables "}))
    assert res.proposal == {"action": "save_memory_note", "text": "likes tables"}
    assert run(tools["propose_memory_note"].run({"note": " "})).proposal is None

    class P:
        n = 0

        async def step(self, o):
            self.n += 1
            return [("propose_memory_note", {"note": "x"})] if self.n == 1 else []

    first = [SimpleNamespace(chunk_id=1, content="c", filename="a.pdf", page_number=1)]
    out = run(run_tool_agent(first, tools, P(), max_steps=3, max_calls=3, top_n=3))
    assert out.proposals == [{"action": "save_memory_note", "text": "x"}]


# ---- websocket approve / reject ----
def test_ws_approve_reject_expired(monkeypatch):
    monkeypatch.setattr(
        chat, "verify_token_claims", lambda t: {"sub": UID, "exp": time.time() + 60}
    )
    monkeypatch.setattr(chat, "get_pool", lambda: object())
    saved = {}

    async def apply(pool, prop):
        saved["text"] = prop.text

    monkeypatch.setattr(chat, "apply_proposal", apply)
    a = chat.proposal_store.create(UID, proposals.ACTION_SAVE_MEMORY, "keep it brief")
    b = chat.proposal_store.create(UID, proposals.ACTION_SAVE_MEMORY, "other")
    other = chat.proposal_store.create("someone-else", proposals.ACTION_SAVE_MEMORY, "x")
    with TestClient(app).websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        ws.receive_json()
        for msg, pid, status in [
            ("approve", a.id, "saved"),
            ("approve", a.id, "expired"),  # already used
            ("reject", b.id, "rejected"),
            ("approve", other.id, "expired"),  # not this user's
        ]:
            ws.send_json({"type": msg, "proposal_id": pid})
            r = ws.receive_json()
            assert r == {"type": "proposal_result", "proposal_id": pid, "status": status}
    assert saved == {"text": "keep it brief"}


# ---- parent-child neighbours ----
def _cand(doc, idx, text):
    return Candidate(
        chunk_id=uuid.uuid4(),
        document_id=doc,
        filename="a.pdf",
        page_number=1,
        chunk_index=idx,
        content=text,
        embedding=[],
        similarity=0.9,
    )


def test_merge_neighbors_and_prompt_uses_context_but_cites_original():
    doc = uuid.uuid4()
    rows = [{"document_id": doc, "chunk_index": i, "content": f"c{i}"} for i in (1, 2, 3, 9)]
    ranked = [_cand(doc, 2, "c2")]
    out = merge_neighbors(ranked, rows, radius=1)
    assert out[0].context_content == "c1\n\nc2\n\nc3" and ranked[0].context_content is None
    assert (
        merge_neighbors([_cand(doc, 20, "z")], rows, 1)[0].context_content == "z"
    )  # no neighbours

    built = prompt_mod.build_prompt("q?", out, similarity_threshold=0.0)
    assert "c1\n\nc2\n\nc3" in built.prompt
    assert built.citations[0].content == "c2"  # snippet stays the matched chunk
