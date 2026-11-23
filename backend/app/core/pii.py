"""Best-effort PII/secret redaction for anything leaving the process (traces)."""

from __future__ import annotations

import re

_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}\b"), "[jwt]"),
    (re.compile(r"\b(?:AIza[\w-]{20,}|sk-[\w-]{16,}|gsk_[\w-]{16,})\b"), "[api-key]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[card]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[ssn]"),
    (re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d\b"), "[phone]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
