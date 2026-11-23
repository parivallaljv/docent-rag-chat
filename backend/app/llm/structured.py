"""Schema-constrained generation: Gemini JSON mode + Pydantic validation,
walking the configured model chain; one corrective retry on invalid output."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ..core.config import settings
from . import gemini_client

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class StructuredGenerationError(Exception):
    pass


async def generate_structured(
    prompt: Any,
    schema: type[T],
    system_instruction: str | None = None,
    model: str | None = None,
    timeout: float | None = None,
) -> T:
    from google.genai import types

    client = gemini_client.get_client()
    config = types.GenerateContentConfig(
        temperature=0.2,
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
    )
    models = [
        model or settings.INSIGHTS_MODEL or settings.CHAT_MODEL,
        *settings.chat_model_fallbacks_list,
    ]
    per_call_timeout = timeout or settings.STRUCTURED_TIMEOUT_SECONDS
    last: Exception | None = None
    for model_name in models:
        for attempt in range(2):  # second attempt = one retry on malformed output
            try:
                resp = await asyncio.wait_for(
                    client.aio.models.generate_content(
                        model=model_name, contents=prompt, config=config
                    ),
                    timeout=per_call_timeout,
                )
                return schema.model_validate_json(resp.text or "")
            except ValidationError as exc:
                last = exc
                logger.warning(
                    "structured output from %s failed validation (attempt %d)",
                    model_name,
                    attempt + 1,
                )
            except Exception as exc:  # noqa: BLE001 -- quota/404/overload: next model
                last = exc
                break
    raise StructuredGenerationError(f"all models failed: {type(last).__name__}") from last
