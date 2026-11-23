import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_current_user_id
from app.main import app
from app.routers import messages

UID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def client():
    app.dependency_overrides[get_current_user_id] = lambda: UID
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_feedback_endpoint(client, monkeypatch):
    monkeypatch.setattr(messages, "get_pool", lambda: object())
    seen = {}

    async def upsert(pool, *, user_id, message_id, rating, comment):
        seen.update(user_id=user_id, rating=rating, comment=comment)
        return seen.get("ok", True)

    monkeypatch.setattr(messages.queries, "upsert_feedback", upsert)
    mid = uuid.uuid4()
    r = client.post(f"/messages/{mid}/feedback", json={"rating": -1, "comment": "  bad  "})
    assert r.status_code == 204 and seen == {"user_id": UID, "rating": -1, "comment": "bad"}
    assert client.post(f"/messages/{mid}/feedback", json={"rating": 5}).status_code == 422
    assert (
        client.post(
            f"/messages/{mid}/feedback", json={"rating": 1, "comment": "x" * 2000}
        ).status_code
        == 422
    )
    seen["ok"] = False
    assert client.post(f"/messages/{mid}/feedback", json={"rating": 1}).status_code == 404


def test_judge_answer_passes_model_and_prompt(monkeypatch):
    from eval import judge

    captured = {}

    async def fake(prompt, schema, system_instruction=None, model=None, **k):
        captured.update(prompt=prompt, model=model, system=system_instruction)
        return judge.Verdict(faithful=True, correct=False, reason="r")

    monkeypatch.setattr(judge, "generate_structured", fake)
    monkeypatch.setenv("JUDGE_MODEL", "judge-x")
    v = asyncio.run(judge.judge_answer("q", "ref", "ctx", "ans"))
    assert v.faithful and not v.correct and captured["model"] == "judge-x"
    assert "<reference>ref</reference>" in captured["prompt"] and captured["system"] == judge.RUBRIC


def test_injection_poisoned_excerpt_is_fenced():
    from app.retrieval.prompt import build_prompt
    from eval import injection

    out = build_prompt(
        "q?", [injection.poisoned(injection.ATTACKS["fake-close-tag"])], similarity_threshold=0.0
    )
    assert out.prompt.count("</context>") == 1  # attack could not close the fence
