import asyncio

import pytest
from pydantic import BaseModel

from app.core.config import settings
from app.llm import structured


class Out(BaseModel):
    x: int


class _Models:
    def __init__(self, behaviours):
        self.calls, self.behaviours = [], behaviours

    async def generate_content(self, model, contents, config):
        self.calls.append(model)
        action = self.behaviours[model]
        if action == "hang":
            await asyncio.sleep(10)
        if action == "error":
            raise RuntimeError("404 NOT_FOUND")

        class R:
            text = action

        return R()


def _client(behaviours):
    models = _Models(behaviours)

    class C:
        class aio:  # noqa: N801
            pass

    C.aio.models = models
    return C, models


def test_slow_model_falls_through_to_next(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MODEL", "m1")
    monkeypatch.setattr(settings, "CHAT_MODEL_FALLBACKS", "m2,m3")
    monkeypatch.setattr(settings, "INSIGHTS_MODEL", "")
    client, models = _client({"m1": "hang", "m2": "error", "m3": '{"x": 7}'})
    monkeypatch.setattr(structured.gemini_client, "get_client", lambda: client)
    out = asyncio.run(structured.generate_structured("p", Out, timeout=0.05))
    assert out.x == 7 and models.calls == ["m1", "m2", "m3"]


def test_all_models_failing_raises_cleanly(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MODEL", "m1")
    monkeypatch.setattr(settings, "CHAT_MODEL_FALLBACKS", "m2")
    client, _ = _client({"m1": "hang", "m2": "error"})
    monkeypatch.setattr(structured.gemini_client, "get_client", lambda: client)
    with pytest.raises(structured.StructuredGenerationError):
        asyncio.run(structured.generate_structured("p", Out, timeout=0.05))


def test_invalid_json_is_retried_once_then_next_model(monkeypatch):
    monkeypatch.setattr(settings, "CHAT_MODEL", "m1")
    monkeypatch.setattr(settings, "CHAT_MODEL_FALLBACKS", "m2")
    client, models = _client({"m1": "not json", "m2": '{"x": 1}'})
    monkeypatch.setattr(structured.gemini_client, "get_client", lambda: client)
    assert asyncio.run(structured.generate_structured("p", Out)).x == 1
    assert models.calls == ["m1", "m1", "m2"]
