import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mcp_server import tools


class Pool: ...


def run(coro):
    return asyncio.run(coro)


def test_search_documents_clamps_k_and_shapes_output(monkeypatch):
    seen = {}

    async def fake_search(pool, *, user_id, query_text, document_id, top_n):
        seen.update(user_id=user_id, top_n=top_n, document_id=document_id)
        return [
            SimpleNamespace(
                document_id=uuid4(),
                filename="a.pdf",
                page_number=2,
                similarity=0.81234,
                content="x" * 5000,
            )
        ]

    monkeypatch.setattr(tools, "search", fake_search)
    out = run(tools.search_documents(Pool(), "u1", "q", k=999))
    assert seen["top_n"] == tools.MAX_K and seen["user_id"] == "u1"
    assert out[0]["page"] == 2 and out[0]["similarity"] == 0.812
    assert len(out[0]["text"]) == tools.SNIPPET_CHARS


def test_list_documents(monkeypatch):
    async def fake(pool, *, user_id):
        return [{"id": uuid4(), "filename": "a.pdf", "status": "ready"}]

    monkeypatch.setattr(tools.queries, "list_documents", fake)
    assert run(tools.list_documents(Pool(), "u1"))[0]["filename"] == "a.pdf"


def test_insight_rejects_bad_kind_and_unready_doc(monkeypatch):
    with pytest.raises(ValueError):
        run(tools.get_document_insight(Pool(), "u", str(uuid4()), "nope"))

    async def doc(pool, *, user_id, document_id):
        return {"filename": "a.pdf", "status": "processing"}

    monkeypatch.setattr(tools.queries, "get_document", doc)
    with pytest.raises(ValueError, match="not ready"):
        run(tools.get_document_insight(Pool(), "u", str(uuid4()), "summary"))


def test_insight_uses_cache(monkeypatch):
    async def doc(pool, *, user_id, document_id):
        return {"filename": "a.pdf", "status": "ready"}

    async def cached(pool, *, user_id, document_id, kind):
        return {"summary": "cached"}

    monkeypatch.setattr(tools.queries, "get_document", doc)
    monkeypatch.setattr(tools.queries, "get_insight", cached)
    assert run(tools.get_document_insight(Pool(), "u", "d", "summary")) == {"summary": "cached"}


def test_server_registers_tools():
    from mcp_server.server import mcp

    names = {t.name for t in run(mcp.list_tools())}
    assert {"search_documents", "list_documents", "get_document_insight"} <= names
