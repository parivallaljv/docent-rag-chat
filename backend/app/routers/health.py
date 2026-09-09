"""GET /health -- used both for Render's health checks and an external
keep-alive cron (free-tier Render services spin down on idle)."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
