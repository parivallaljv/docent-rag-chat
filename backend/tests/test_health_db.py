from fastapi.testclient import TestClient

from app.main import app
from app.routers import health


class _Conn:
    async def fetchval(self, q):
        return 1


class _Acquire:
    async def __aenter__(self):
        return _Conn()

    async def __aexit__(self, *a):
        return False


class _Pool:
    def acquire(self):
        return _Acquire()


def test_health_db_ok_and_down(monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(health, "get_pool", lambda: _Pool())
    assert c.get("/health/db").json() == {"status": "ok", "db": "ok"}

    def boom():
        raise RuntimeError("no pool")

    monkeypatch.setattr(health, "get_pool", boom)
    assert c.get("/health/db").status_code == 503
