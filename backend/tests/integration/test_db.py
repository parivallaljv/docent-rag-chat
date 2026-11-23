"""Real-Postgres checks for db/queries.py. Skipped unless TEST_DB_URL points at a
database with migrations 001, 005, 006, 007, 008, 009 applied (plus an `auth.users` table; see
backend/docker/00_auth_stub.sql). CI runs it against a pgvector service container."""

import asyncio
import json
import os
import random
import uuid

import pytest

URL = os.environ.get("TEST_DB_URL")
pytestmark = [pytest.mark.integration, pytest.mark.skipif(not URL, reason="TEST_DB_URL not set")]


def _vec(seed):
    r = random.Random(seed)
    v = [r.random() for _ in range(768)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


async def _scenario():
    import asyncpg
    from pgvector.asyncpg import register_vector

    from app.db import queries

    pool = await asyncpg.create_pool(URL, init=register_vector, min_size=1, max_size=3)
    try:
        u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
        async with pool.acquire() as c:
            await c.executemany(
                "insert into auth.users(id) values($1)", [(uuid.UUID(u1),), (uuid.UUID(u2),)]
            )
        d = await queries.insert_document(
            pool, user_id=u1, filename="a.pdf", storage_path=f"{u1}/a.pdf"
        )
        did = d["id"]
        texts = [
            "The refund window is thirty days.",
            "Adam optimizer with warmup.",
            "Sine cosine positions.",
        ]
        chunks = [
            {"page_number": i + 1, "chunk_index": i, "content": t, "embedding": _vec(i)}
            for i, t in enumerate(texts)
        ]
        # idempotent atomic swap + status flip
        await queries.replace_chunks_and_mark_ready(
            pool, document_id=did, user_id=u1, chunks=chunks
        )
        await queries.replace_chunks_and_mark_ready(
            pool, document_id=did, user_id=u1, chunks=chunks
        )
        assert len(await queries.get_document_chunks(pool, user_id=u1, document_id=did)) == 3
        assert (await queries.get_document(pool, user_id=u1, document_id=did))["status"] == "ready"

        # dense + keyword search, scoping, hostile query text
        dense = await queries.search_chunks(pool, user_id=u1, query_embedding=_vec(1), limit=3)
        assert dense[0]["content"].startswith("Adam") and dense[0]["similarity"] > 0.99
        kw = await queries.keyword_search_chunks(
            pool, user_id=u1, query_text="refund window", limit=5
        )
        assert [r["page_number"] for r in kw] == [1]
        assert await queries.keyword_search_chunks(pool, user_id=u2, query_text="refund") == []
        await queries.keyword_search_chunks(pool, user_id=u1, query_text="!!! ' \" ) (")

        # neighbouring chunks: window, ordering, per-user isolation
        nb = await queries.get_neighbor_chunks(pool, user_id=u1, wanted=[(did, 1)], radius=1)
        assert [r["chunk_index"] for r in nb] == [0, 1, 2]
        nb0 = await queries.get_neighbor_chunks(pool, user_id=u1, wanted=[(did, 0)], radius=1)
        assert [r["chunk_index"] for r in nb0] == [0, 1]
        assert (
            await queries.get_neighbor_chunks(pool, user_id=u2, wanted=[(did, 1)], radius=1) == []
        )
        assert await queries.get_neighbor_chunks(pool, user_id=u1, wanted=[], radius=1) == []

        # chats: isolation, titling, ordering, cascade
        ch = await queries.create_chat(pool, user_id=u1)
        assert await queries.get_chat(pool, user_id=u2, chat_id=ch["id"]) is None
        await queries.add_message(
            pool, user_id=u1, chat_id=ch["id"], role="user", content="  What is   the refund?\n"
        )
        await queries.add_message(
            pool,
            user_id=u1,
            chat_id=ch["id"],
            role="assistant",
            content="30 days [1]",
            citations=[{"marker": 1}],
        )
        assert (await queries.get_chat(pool, user_id=u1, chat_id=ch["id"]))[
            "title"
        ] == "What is the refund?"
        msgs = await queries.list_messages(pool, user_id=u1, chat_id=ch["id"])
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert json.loads(msgs[1]["citations"])[0]["marker"] == 1
        assert await queries.list_messages(pool, user_id=u2, chat_id=ch["id"]) == []

        # feedback: only on your own assistant answers; re-rating updates
        ans_id, user_msg_id = msgs[1]["id"], msgs[0]["id"]
        assert await queries.upsert_feedback(
            pool, user_id=u1, message_id=ans_id, rating=-1, comment="wrong"
        )
        assert await queries.upsert_feedback(
            pool, user_id=u1, message_id=ans_id, rating=1, comment=None
        )
        assert not await queries.upsert_feedback(
            pool, user_id=u2, message_id=ans_id, rating=1, comment=None
        )
        assert not await queries.upsert_feedback(
            pool, user_id=u1, message_id=user_msg_id, rating=1, comment=None
        )
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT rating FROM message_feedback") == 1

        # usage accounting (migration 009)
        await queries.add_usage(
            pool,
            user_id=u1,
            kind="chat",
            model="m",
            prompt_tokens=10,
            completion_tokens=5,
            cost_usd=0.001,
        )
        await queries.add_usage(
            pool,
            user_id=u1,
            kind="chat",
            model="m",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=0.002,
        )
        totals, daily = await queries.usage_summary(pool, user_id=u1, days=30)
        assert (
            totals["turns"] == 2
            and totals["prompt_tokens"] == 11
            and abs(totals["cost_usd"] - 0.003) < 1e-9
        )
        assert len(daily) == 1 and daily[0]["turns"] == 2
        assert (await queries.usage_summary(pool, user_id=u2, days=30))[0]["turns"] == 0

        # memory + chat summary + tags (migration 008)
        assert await queries.get_memory(pool, user_id=u1) is None
        await queries.upsert_memory(pool, user_id=u1, content="a")
        await queries.upsert_memory(pool, user_id=u1, content="b")
        assert await queries.get_memory(pool, user_id=u1) == "b"
        assert await queries.get_memory(pool, user_id=u2) is None
        await queries.delete_memory(pool, user_id=u1)
        assert await queries.get_memory(pool, user_id=u1) is None
        import datetime as _dt

        ts = _dt.datetime(2026, 1, 1, tzinfo=_dt.UTC)
        assert await queries.get_chat_summary(pool, user_id=u1, chat_id=ch["id"]) == (None, None)
        await queries.set_chat_summary(pool, user_id=u1, chat_id=ch["id"], summary="S", upto=ts)
        assert await queries.get_chat_summary(pool, user_id=u1, chat_id=ch["id"]) == ("S", ts)
        assert await queries.get_chat_summary(pool, user_id=u2, chat_id=ch["id"]) == (None, None)
        assert not await queries.delete_chat(pool, user_id=u2, chat_id=ch["id"])
        assert await queries.delete_chat(pool, user_id=u1, chat_id=ch["id"])

        # insights upsert
        await queries.upsert_insight(
            pool, user_id=u1, document_id=did, kind="quiz", result={"v": 1}
        )
        await queries.upsert_insight(
            pool, user_id=u1, document_id=did, kind="quiz", result={"v": 2}
        )
        assert (await queries.get_insight(pool, user_id=u1, document_id=did, kind="quiz"))["v"] == 2

        # retry / stuck-recovery / delete
        assert (
            await queries.mark_pending_if_failed(pool, user_id=u1, document_id=did) is None
        )  # ready, not failed
        await queries.update_document_status(
            pool, document_id=did, status="failed", error_message="x"
        )
        assert (
            await queries.mark_pending_if_failed(pool, user_id=u2, document_id=did) is None
        )  # not theirs
        row = await queries.mark_pending_if_failed(pool, user_id=u1, document_id=did)
        assert row["status"] == "pending" and row["error_message"] is None
        assert await queries.get_stuck_documents(pool, older_than_minutes=10) == []  # too recent
        async with pool.acquire() as c:
            await c.execute(
                "update documents set created_at = now() - interval '1 hour' where id = $1", did
            )
        assert [
            r["id"] for r in await queries.get_stuck_documents(pool, older_than_minutes=10)
        ] == [did]
        assert await queries.delete_document(pool, user_id=u2, document_id=did) is None
        assert await queries.delete_document(pool, user_id=u1, document_id=did) == f"{u1}/a.pdf"
        assert await queries.get_document_chunks(pool, user_id=u1, document_id=did) == []  # cascade
    finally:
        await pool.close()


def test_queries_against_real_postgres():
    asyncio.run(_scenario())
