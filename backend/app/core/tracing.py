"""Optional Langfuse tracing (opt-in: set LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY).

Sends one trace per chat turn through Langfuse's public ingestion API using plain
HTTPS (no SDK dependency). PRIVACY: by default only metadata is sent (stage timings,
token counts, model, prompt version, outcome). Message text and answers are sent only
when LANGFUSE_CAPTURE_CONTENT=true, and even then are passed through PII redaction."""

from __future__ import annotations

import base64
import datetime as dt
import logging
import uuid

import httpx

from .background import spawn
from .config import settings
from .pii import redact

logger = logging.getLogger(__name__)

_SKIP_STAGES = {"total", "ttft"}  # total/ttft overlap other stages


def tracing_enabled() -> bool:
    return bool(settings.LANGFUSE_PUBLIC_KEY and settings.LANGFUSE_SECRET_KEY)


def _iso(t: dt.datetime) -> str:
    return t.isoformat().replace("+00:00", "Z")


def build_events(
    *,
    started: dt.datetime,
    stages: dict[str, float],
    attrs: dict,
    outcome: str,
    prompt_version: str,
    input_text: str | None = None,
    output_text: str | None = None,
) -> list[dict]:
    trace_id = uuid.uuid4().hex
    now = dt.datetime.now(dt.UTC)
    meta = {k: v for k, v in attrs.items() if isinstance(v, (int, float, str, bool, list))}
    meta.update(outcome=outcome, prompt_version=prompt_version, stages_s=stages)
    body: dict = {
        "id": trace_id,
        "name": "chat_turn",
        "timestamp": _iso(started),
        "metadata": meta,
        "tags": [f"prompt:{prompt_version}", f"outcome:{outcome}"],
    }
    if settings.LANGFUSE_CAPTURE_CONTENT:
        body["input"] = redact(input_text or "")
        body["output"] = redact(output_text or "")
    events = [
        {"id": uuid.uuid4().hex, "type": "trace-create", "timestamp": _iso(now), "body": body}
    ]
    cursor = started
    for name, seconds in stages.items():
        if name in _SKIP_STAGES:
            continue
        end = cursor + dt.timedelta(seconds=seconds)
        span = {
            "id": uuid.uuid4().hex,
            "traceId": trace_id,
            "name": name,
            "startTime": _iso(cursor),
            "endTime": _iso(end),
        }
        if name == "generate":
            span.update(
                model=attrs.get("model"),
                usageDetails={
                    "input": attrs.get("prompt_tokens_approx", 0),
                    "output": attrs.get("completion_tokens_approx", 0),
                },
            )
            kind = "generation-create"
        else:
            kind = "span-create"
        events.append({"id": uuid.uuid4().hex, "type": kind, "timestamp": _iso(now), "body": span})
        cursor = end
    return events


async def _post(events: list[dict]) -> None:
    token = base64.b64encode(
        f"{settings.LANGFUSE_PUBLIC_KEY}:{settings.LANGFUSE_SECRET_KEY}".encode()
    ).decode()
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{settings.LANGFUSE_HOST.rstrip('/')}/api/public/ingestion",
            headers={"Authorization": f"Basic {token}"},
            json={"batch": events},
        )
        if r.status_code >= 400:
            logger.warning("langfuse ingestion returned %s", r.status_code)


def export_trace(trace, outcome: str, prompt_version: str, input_text=None, output_text=None):
    """Fire-and-forget; a tracing outage can never affect a chat turn."""
    if not tracing_enabled():
        return
    events = build_events(
        started=trace.started_at,
        stages=trace.stages,
        attrs=trace.attrs,
        outcome=outcome,
        prompt_version=prompt_version,
        input_text=input_text,
        output_text=output_text,
    )
    spawn(_post(events), "langfuse export")
