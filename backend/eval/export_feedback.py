"""Turn downvoted answers into candidate eval rows.

    python -m eval.export_feedback > eval/candidates.jsonl

Reads message_feedback joined to the question that preceded each answer.
Rows are CANDIDATES: a human must add the reference `evidence` (and the relevant
document/phrase) before moving a row into dataset.jsonl. Needs SUPABASE_DB_URL
(service connection; reads all users' feedback, so run it only on your own data)."""

from __future__ import annotations

import asyncio
import json
import sys

import asyncpg

from app.core.config import settings

QUERY = """
SELECT f.rating, f.comment, a.id AS message_id, a.content AS answer, a.citations,
       (SELECT u.content FROM messages u
         WHERE u.chat_id = a.chat_id AND u.role = 'user' AND u.created_at <= a.created_at
         ORDER BY u.created_at DESC LIMIT 1) AS question
FROM message_feedback f JOIN messages a ON a.id = f.message_id
WHERE f.rating = $1 ORDER BY f.created_at DESC LIMIT 200
"""


async def main(rating: int = -1) -> int:
    conn = await asyncpg.connect(settings.SUPABASE_DB_URL)
    try:
        rows = await conn.fetch(QUERY, rating)
    finally:
        await conn.close()
    for r in rows:
        if not r["question"]:
            continue
        print(
            json.dumps(
                {
                    "id": f"fb-{str(r['message_id'])[:8]}",
                    "question": r["question"],
                    "evidence": "",  # TODO: human-written reference fact
                    "doc": "",
                    "bad_answer": r["answer"],
                    "user_comment": r["comment"],
                    "source": "user_feedback",
                }
            )
        )
    print(f"exported {len(rows)} rows", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
