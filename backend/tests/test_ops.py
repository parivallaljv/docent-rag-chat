import json
import logging

from fastapi.testclient import TestClient

from app.core.cache import TTLCache
from app.core.config import settings
from app.core.logging import JsonFormatter, request_id_var
from app.core.metrics import STAGE_SECONDS, Trace
from app.core.rate_limit import SlidingWindowLimiter
from app.main import app


def test_ttl_cache_expiry_and_lru():
    now = [0.0]
    c = TTLCache(2, 10, clock=lambda: now[0])
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1  # refreshes a's recency
    c.set("c", 3)  # evicts b (least recently used)
    assert c.get("b") is None and c.get("a") == 1 and c.get("c") == 3
    now[0] = 11
    assert c.get("a") is None
    assert len(TTLCache(0, 10)) == 0


def test_sliding_window_limiter():
    now = [0.0]
    lim = SlidingWindowLimiter(clock=lambda: now[0])
    assert [lim.allow("u", 2, 60) for _ in range(3)] == [True, True, False]
    assert lim.allow("other", 2, 60)  # keys are independent
    now[0] = 61
    assert lim.allow("u", 2, 60)


def test_json_log_has_request_id_and_extras():
    token = request_id_var.set("abc123")
    try:
        rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("w",), None)
        rec.stages_s = {"retrieve": 0.1}
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello w" and out["request_id"] == "abc123"
    assert out["stages_s"] == {"retrieve": 0.1} and out["level"] == "INFO"


def test_trace_records_stages():
    before = STAGE_SECONDS.labels(stage="unit")._sum.get()
    t = Trace(user="u")
    with t.stage("unit"):
        pass
    t.finish("ok")
    assert "unit" in t.stages and "total" in t.stages
    assert STAGE_SECONDS.labels(stage="unit")._sum.get() >= before


def test_http_endpoints(monkeypatch):
    client = TestClient(app)  # no `with`: lifespan (DB pool) not started
    r = client.get("/status", headers={"x-request-id": "rid-1"})
    assert r.status_code == 200 and r.headers["x-request-id"] == "rid-1"
    assert set(r.json()["quota"]) == {"day", "used", "limit"}

    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    assert client.get("/metrics").status_code == 404  # disabled by default
    monkeypatch.setattr(settings, "METRICS_TOKEN", "s3cret")
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"authorization": "Bearer nope"}).status_code == 401
    ok = client.get("/metrics", headers={"authorization": "Bearer s3cret"})
    assert ok.status_code == 200 and "docent_stage_seconds" in ok.text
