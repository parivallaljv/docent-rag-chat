"""Post-generation citation checks: which numbered excerpts did the model
actually cite, and did it cite numbers that don't exist?"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

# Matches [1], [1][3] (two matches), [1, 3] / [1,3], and the full-width
# 【1】 form some models (seen from Groq) emit instead of ASCII brackets.
_MARKER_GROUP_RE = re.compile(r"[\[【［]\s*(\d+(?:\s*[,，]\s*\d+)*)\s*[\]】］]")


def extract_markers(answer: str) -> list[int]:
    """Distinct cited excerpt numbers, in order of first appearance."""
    seen: dict[int, None] = {}
    for m in _MARKER_GROUP_RE.finditer(answer):
        for num in re.split(r"[,，]", m.group(1)):
            seen.setdefault(int(num), None)
    return list(seen)


def reconcile_citations(
    answer: str, available_markers: Iterable[int]
) -> tuple[list[int], list[int]]:
    """Return (valid_cited_markers, invalid_markers) for an answer, given the
    excerpt numbers that were actually in the prompt."""
    available = set(available_markers)
    cited = extract_markers(answer)
    return [n for n in cited if n in available], [n for n in cited if n not in available]


def select_cited(citations: Sequence, valid_markers: Iterable[int]) -> list:
    """Citations whose `.marker` was cited, ordered by first citation."""
    by_marker = {c.marker: c for c in citations}
    return [by_marker[n] for n in valid_markers if n in by_marker]
