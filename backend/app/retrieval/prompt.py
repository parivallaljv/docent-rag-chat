"""Assembles the final grounded-answer prompt: numbers retrieved chunks as
[1], [2], ... for citation, folds in recent chat history, enforces an
approximate token budget (dropping the lowest-similarity chunks first when
over budget), and implements the "no relevant context" guardrail.

Pure logic -- no external API calls -- so this whole module is unit-testable
without any credentials. Candidates may be either db.models-style objects
with attributes (chunk_id, document_id, filename, page_number, content,
similarity) -- e.g. retrieval.search.Candidate, ideally already passed
through retrieval.rerank.mmr_rerank -- or plain dicts with the same keys
(handy for tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Union

from ..ingestion.chunker import approx_token_count

DEFAULT_SIMILARITY_THRESHOLD = 0.65
DEFAULT_MAX_PROMPT_TOKENS = 4000
DEFAULT_HISTORY_TURNS = 5

# Returned by build_prompt() when the guardrail fails. Callers should check
# for this sentinel and short-circuit to the canned "no relevant context"
# response instead of calling Gemini at all.
NO_CONTEXT_SENTINEL = "__NO_RELEVANT_CONTEXT__"

NO_CONTEXT_MESSAGE = (
    "I couldn't find relevant information in your documents to answer that. "
    "Try rephrasing your question, or upload a document that covers this topic."
)

SYSTEM_PREAMBLE = (
    "You are a helpful assistant answering questions using ONLY the numbered "
    "context excerpts below, taken from the user's own uploaded documents. "
    "Cite every factual claim with the bracketed number(s) of the excerpt(s) "
    "it came from, e.g. [1] or [1][3]. If the excerpts don't contain the "
    "answer, say so plainly instead of guessing."
)


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class ContextChunk:
    marker: int
    chunk_id: Any
    document_id: Any
    filename: str
    page_number: int
    content: str
    similarity: float


@dataclass
class AssembledPrompt:
    prompt: str
    system_instruction: str
    citations: List[ContextChunk]


def _get(candidate: Any, field: str) -> Any:
    if isinstance(candidate, dict):
        return candidate[field]
    return getattr(candidate, field)


def passes_relevance_guardrail(
    ranked_candidates: Sequence[Any], threshold: float = DEFAULT_SIMILARITY_THRESHOLD
) -> bool:
    """True if there's at least one candidate and its (top / best-ranked)
    similarity clears the guardrail threshold -- i.e. it's worth generating
    an answer at all rather than returning the canned "no context" reply."""
    if not ranked_candidates:
        return False
    return _get(ranked_candidates[0], "similarity") >= threshold


def _format_history(history: Sequence[ChatTurn], max_turns: int = DEFAULT_HISTORY_TURNS) -> str:
    if not history:
        return ""
    recent = list(history)[-max_turns:]
    lines = [f"{turn.role.capitalize()}: {turn.content}" for turn in recent]
    return "Recent conversation:\n" + "\n".join(lines)


def _fit_chunks_to_budget(candidates: Sequence[Any], max_tokens: int, reserved_tokens: int) -> List[Any]:
    """Greedily keep candidates (assumed already ordered best-first) until
    the token budget runs out. The lowest-similarity chunks -- the tail of
    the best-first ordering -- are dropped first. The single best candidate
    is always kept even if it alone doesn't fit, so a passed guardrail never
    results in an empty context."""
    budget = max_tokens - reserved_tokens
    kept: List[Any] = []
    used = 0
    for c in candidates:
        tokens = approx_token_count(_get(c, "content"))
        if kept and used + tokens > budget:
            break
        kept.append(c)
        used += tokens
    return kept


def build_prompt(
    query: str,
    ranked_candidates: Sequence[Any],
    history: Optional[Sequence[ChatTurn]] = None,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_prompt_tokens: int = DEFAULT_MAX_PROMPT_TOKENS,
    history_turns: int = DEFAULT_HISTORY_TURNS,
) -> Union[str, AssembledPrompt]:
    """Build the final prompt from MMR-ranked candidates (best-first).

    Returns the NO_CONTEXT_SENTINEL string if the guardrail fails; otherwise
    returns an AssembledPrompt with the prompt text, system instruction, and
    the ContextChunk citation list (bracket markers matching the numbers
    used in the prompt text).
    """
    if not passes_relevance_guardrail(ranked_candidates, similarity_threshold):
        return NO_CONTEXT_SENTINEL

    history = history or []
    history_text = _format_history(history, history_turns)
    reserved = (
        approx_token_count(SYSTEM_PREAMBLE)
        + approx_token_count(query)
        + approx_token_count(history_text)
    )

    fitted = _fit_chunks_to_budget(ranked_candidates, max_prompt_tokens, reserved)

    context_lines: List[str] = []
    citations: List[ContextChunk] = []
    for i, c in enumerate(fitted, start=1):
        content = _get(c, "content")
        context_lines.append(f"[{i}] {content}")
        citations.append(
            ContextChunk(
                marker=i,
                chunk_id=_get(c, "chunk_id"),
                document_id=_get(c, "document_id"),
                filename=_get(c, "filename"),
                page_number=_get(c, "page_number"),
                content=content,
                similarity=_get(c, "similarity"),
            )
        )

    parts = [SYSTEM_PREAMBLE]
    if history_text:
        parts.append(history_text)
    parts.append("Context:\n" + "\n\n".join(context_lines))
    parts.append(f"Question: {query}")

    return AssembledPrompt(
        prompt="\n\n".join(parts),
        system_instruction=SYSTEM_PREAMBLE,
        citations=citations,
    )
