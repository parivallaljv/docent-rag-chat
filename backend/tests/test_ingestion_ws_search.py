import asyncio
import time
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.auth import TokenVerificationError, get_current_user_id
from app.core.config import settings
from app.ingestion import ocr, pipeline
from app.ingestion.chunker import chunk_pages
from app.main import app
from app.retrieval import search as search_mod
from app.routers import chat
from app.routers import documents as docs_router

UID = "11111111-1111-1111-1111-111111111111"
DOC = uuid.uuid4()


# ---------------- WebSocket: expiry, ping, bad token ----------------


def test_ws_ping_pong_and_expiry_close(monkeypatch):
    monkeypatch.setattr(
        chat, "verify_token_claims", lambda t: {"sub": UID, "exp": time.time() + 0.6}
    )
    with TestClient(app).websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": "t"})
        assert ws.receive_json() == {"type": "auth_ok"}
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        with pytest.raises(WebSocketDisconnect) as exc:  # closed once the token expires
            ws.receive_json()
        assert exc.value.code == 1008


def test_ws_rejects_bad_token(monkeypatch):
    def boom(token):
        raise TokenVerificationError("Invalid token")

    monkeypatch.setattr(chat, "verify_token_claims", boom)
    with TestClient(app).websocket_connect("/chat/ws") as ws:
        ws.send_json({"type": "auth", "token": "bad"})
        assert ws.receive_json()["type"] == "auth_error"


def test_ws_rejects_disallowed_origin():
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect(
            "/chat/ws", headers={"origin": "https://evil.example"}
        ) as ws:
            ws.receive_json()


def test_cors_is_explicit():
    r = TestClient(app).options(
        "/documents",
        headers={
            "origin": settings.allowed_origins_list[0],
            "access-control-request-method": "PUT",
            "access-control-request-headers": "authorization",
        },
    )
    assert "PUT" not in r.headers.get("access-control-allow-methods", "")


# ---------------- ingestion pipeline ----------------


class Recorder:
    def __init__(self):
        self.statuses, self.replaced = [], None


def _patch_pipeline(monkeypatch, pages, ocr_pages=None, ocr_error=False):
    rec = Recorder()

    async def status(pool, document_id, status, error_message=None):
        rec.statuses.append((status, error_message))

    async def replace(pool, document_id, user_id, chunks):
        rec.replaced = chunks

    async def embed(texts):
        return [[0.0] * 768 for _ in texts]

    async def fake_ocr(pdf):
        if ocr_error:
            raise ocr.OcrUnavailable("off")
        return ocr_pages or []

    monkeypatch.setattr(pipeline, "get_pool", lambda: object())
    monkeypatch.setattr(pipeline.queries, "update_document_status", status)
    monkeypatch.setattr(pipeline.queries, "replace_chunks_and_mark_ready", replace)
    monkeypatch.setattr(pipeline, "download_from_storage", lambda p: b"%PDF")
    monkeypatch.setattr(pipeline, "extract_pages", lambda b: iter(pages))
    monkeypatch.setattr(pipeline, "embed_chunks", embed)
    monkeypatch.setattr(pipeline, "ocr_pdf", fake_ocr)
    return rec


def _run(path=f"{UID}/a.pdf"):
    asyncio.run(pipeline.run_ingestion_pipeline(DOC, UID, path))


def test_pipeline_happy_path_is_atomic_swap(monkeypatch):
    rec = _patch_pipeline(monkeypatch, [(1, "Hello world. " * 20)])
    _run()
    assert rec.replaced and rec.statuses == [("processing", None)]  # 'ready' set inside the swap


def test_pipeline_ocr_fallback_for_scanned_pdf(monkeypatch):
    rec = _patch_pipeline(monkeypatch, [(1, "")], ocr_pages=[(1, "Scanned text here. " * 10)])
    _run()
    assert rec.replaced and all(s != "failed" for s, _ in rec.statuses)


def test_pipeline_fails_cleanly_when_ocr_unavailable(monkeypatch):
    rec = _patch_pipeline(monkeypatch, [(1, "")], ocr_error=True)
    _run()
    assert rec.replaced is None
    assert rec.statuses[-1][0] == "failed" and "No extractable text" in rec.statuses[-1][1]


def test_pipeline_rejects_foreign_storage_path(monkeypatch):
    rec = _patch_pipeline(monkeypatch, [(1, "x")])
    _run(path="someone-else/a.pdf")
    assert rec.statuses == [("failed", "This file path doesn't belong to your account.")]


def test_recover_stuck_documents(monkeypatch):
    ran = []

    async def stuck(pool, older_than_minutes):
        assert older_than_minutes == settings.STUCK_DOCUMENT_MINUTES
        return [
            {"id": 1, "user_id": UID, "storage_path": "p1"},
            {"id": 2, "user_id": UID, "storage_path": "p2"},
        ]

    async def fake_run(document_id, user_id, storage_path):
        ran.append(storage_path)

    monkeypatch.setattr(pipeline, "get_pool", lambda: object())
    monkeypatch.setattr(pipeline.queries, "get_stuck_documents", stuck)
    monkeypatch.setattr(pipeline, "run_ingestion_pipeline", fake_run)
    assert asyncio.run(pipeline.recover_stuck_documents()) == 2 and ran == ["p1", "p2"]


# ---------------- OCR ----------------


def test_ocr_filters_pages_and_respects_limits(monkeypatch):
    async def fake(contents, schema, system_instruction=None, **kwargs):
        return ocr.OcrResult(
            pages=[
                ocr.OcrPage(page=2, text=" two "),
                ocr.OcrPage(page=1, text="one"),
                ocr.OcrPage(page=3, text="  "),
                ocr.OcrPage(page=999, text="far"),
            ]
        )

    monkeypatch.setattr(ocr, "generate_structured", fake)
    assert asyncio.run(ocr.ocr_pdf(b"%PDF")) == [(1, "one"), (2, "two")]
    with pytest.raises(ocr.OcrUnavailable):
        asyncio.run(ocr.ocr_pdf(b"x" * (ocr.MAX_INLINE_BYTES + 1)))
    monkeypatch.setattr(settings, "OCR_FALLBACK", False)
    with pytest.raises(ocr.OcrUnavailable):
        asyncio.run(ocr.ocr_pdf(b"%PDF"))


def test_chunker_accepts_ocr_pages():
    assert chunk_pages([(1, "word " * 30)])


# ---------------- documents router: delete + retry ----------------


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user_id] = lambda: UID
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_delete_document(client, monkeypatch):
    removed = []
    monkeypatch.setattr(docs_router, "get_pool", lambda: object())

    async def delete(pool, user_id, document_id):
        return f"{UID}/a.pdf" if document_id == DOC else None

    monkeypatch.setattr(docs_router.queries, "delete_document", delete)
    monkeypatch.setattr(docs_router, "delete_from_storage", lambda p: removed.append(p))
    assert client.delete(f"/documents/{DOC}").status_code == 204 and removed == [f"{UID}/a.pdf"]
    assert client.delete(f"/documents/{uuid.uuid4()}").status_code == 404

    def storage_down(p):
        raise RuntimeError("storage down")

    monkeypatch.setattr(docs_router, "delete_from_storage", storage_down)
    assert client.delete(f"/documents/{DOC}").status_code == 204  # DB row gone is what matters


def test_retry_only_failed_documents(client, monkeypatch):
    ran = []
    monkeypatch.setattr(docs_router, "get_pool", lambda: object())

    async def mark(pool, user_id, document_id):
        if document_id != DOC:
            return None
        import datetime as dt

        return {
            "id": DOC,
            "filename": "a.pdf",
            "storage_path": f"{UID}/a.pdf",
            "status": "pending",
            "error_message": None,
            "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        }

    async def fake_run(document_id, user_id, storage_path):
        ran.append(storage_path)

    monkeypatch.setattr(docs_router.queries, "mark_pending_if_failed", mark)
    monkeypatch.setattr(docs_router, "run_ingestion_pipeline", fake_run)
    r = client.post(f"/documents/{DOC}/retry")
    assert r.status_code == 202 and r.json()["status"] == "pending" and ran == [f"{UID}/a.pdf"]
    assert client.post(f"/documents/{uuid.uuid4()}/retry").status_code == 409


# ---------------- retrieval/search.py ----------------


class Emb:
    def __init__(self, v):
        self.v = v

    def to_list(self):
        return self.v


def _row(i, vec, content="c"):
    return {
        "id": i,
        "document_id": DOC,
        "filename": "a.pdf",
        "page_number": i,
        "chunk_index": i,
        "content": content,
        "embedding": Emb(vec),
        "similarity": 0.0,
    }


def _patch_search(monkeypatch, dense, keyword, keyword_error=None):
    async def embed(text):
        return [1.0, 0.0]

    async def s_dense(pool, **k):
        return dense

    async def s_kw(pool, **k):
        if keyword_error:
            raise keyword_error
        return keyword

    monkeypatch.setattr(search_mod, "embed_query", embed)
    monkeypatch.setattr(search_mod.queries, "search_chunks", s_dense)
    monkeypatch.setattr(search_mod.queries, "keyword_search_chunks", s_kw)
    monkeypatch.setattr(settings, "QUERY_REWRITE", False)


def _search():
    return asyncio.run(search_mod.search(object(), user_id=UID, query_text="q", top_n=5))


def test_search_hybrid_fuses_and_computes_true_cosine(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH", True)
    a, b, c = _row(1, [1.0, 0.0]), _row(2, [0.0, 1.0]), _row(3, [0.6, 0.8])
    _patch_search(monkeypatch, dense=[a, c], keyword=[b, a])
    out = _search()
    assert [x.chunk_id for x in out][0] == 1  # in both lists -> first
    assert {x.chunk_id for x in out} == {1, 2, 3}
    sims = {x.chunk_id: x.similarity for x in out}
    assert sims[2] == pytest.approx(0.0) and sims[3] == pytest.approx(
        0.6
    )  # keyword-only hit still gets cosine


def test_search_dense_only_when_hybrid_off(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH", False)
    _patch_search(monkeypatch, dense=[_row(1, [1.0, 0.0])], keyword=[_row(2, [0.0, 1.0])])
    assert [x.chunk_id for x in _search()] == [1]


def test_search_falls_back_when_migration_missing(monkeypatch):
    monkeypatch.setattr(settings, "HYBRID_SEARCH", True)
    _patch_search(
        monkeypatch,
        dense=[_row(1, [1.0, 0.0])],
        keyword=[],
        keyword_error=asyncpg.UndefinedColumnError("content_tsv"),
    )
    assert [x.chunk_id for x in _search()] == [1]
