"""GET /health (Render health check / keep-alive), GET /status (today's AI
budget) and GET /metrics (Prometheus; only served when METRICS_TOKEN is set)."""

import hmac

from fastapi import APIRouter, Header, HTTPException, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ..core.config import settings
from ..core.rate_limit import quota_status

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/status")
async def status() -> dict:
    return {"status": "ok", "quota": quota_status()}


@router.get("/metrics")
async def metrics(authorization: str = Header(default="")) -> Response:
    token = settings.METRICS_TOKEN
    # 404 (not 401) when disabled so the endpoint's existence isn't advertised.
    if not token:
        raise HTTPException(status_code=404)
    if not hmac.compare_digest(authorization, f"Bearer {token}"):
        raise HTTPException(status_code=401)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
