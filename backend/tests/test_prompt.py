"""Unit tests for app.retrieval.prompt: the similarity-threshold guardrail
and token-budget-aware prompt assembly. Pure logic, synthetic candidates
(plain dicts), no credentials or DB needed.
"""
from app.retrieval.prompt import (
    NO_CONTEXT_SENTINEL,
    AssembledPrompt,
    ChatTurn,
    build_prompt,
    passes_relevance_guardrail,
)


def _chunk(marker_seed, content, similarity, page_number=1):
    return {
        "chunk_id": f"chunk-{marker_seed}",
        "document_id": "doc-1",
        "filename": "example.pdf",
        "page_number": page_number,
        "content": content,
        "similarity": similarity,
    }


# --- Guardrail ---


def test_guardrail_blocks_when_no_candidates():
    assert passes_relevance_guardrail([], threshold=0.65) is False


def test_guardrail_blocks_low_top_similarity():
    candidates = [_chunk(1, "irrelevant text", similarity=0.40)]
    assert passes_relevance_guardrail(candidates, threshold=0.65) is False


def test_guardrail_allows_high_top_similarity():
    candidates = [_chunk(1, "relevant text", similarity=0.90)]
    assert passes_relevance_guardrail(candidates, threshold=0.65) is True


def test_guardrail_is_exact_boundary_inclusive():
    candidates = [_chunk(1, "borderline", similarity=0.65)]
    assert passes_relevance_guardrail(candidates, threshold=0.65) is True


def test_build_prompt_returns_sentinel_when_guardrail_fails():
    candidates = [_chunk(1, "irrelevant text", similarity=0.2)]
    result = build_prompt("What is the refund policy?", candidates, similarity_threshold=0.65)
    assert result == NO_CONTEXT_SENTINEL


def test_build_prompt_returns_sentinel_for_empty_candidates():
    result = build_prompt("Anything?", [], similarity_threshold=0.65)
    assert result == NO_CONTEXT_SENTINEL


# --- Successful assembly ---


def test_build_prompt_assembles_numbered_context_and_citations():
    candidates = [
        _chunk(1, "The refund window is 30 days.", similarity=0.92, page_number=2),
        _chunk(2, "Refunds are processed within 5 business days.", similarity=0.80, page_number=3),
    ]
    result = build_prompt("What is the refund policy?", candidates, similarity_threshold=0.65)

    assert isinstance(result, AssembledPrompt)
    assert "[1] The refund window is 30 days." in result.prompt
    assert "[2] Refunds are processed within 5 business days." in result.prompt
    assert "Question: What is the refund policy?" in result.prompt

    assert [c.marker for c in result.citations] == [1, 2]
    assert result.citations[0].page_number == 2
    assert result.citations[1].filename == "example.pdf"


def test_build_prompt_includes_history_when_present():
    candidates = [_chunk(1, "Some fact.", similarity=0.9)]
    history = [ChatTurn(role="user", content="Hi"), ChatTurn(role="assistant", content="Hello!")]
    result = build_prompt("Follow up question", candidates, history=history, similarity_threshold=0.65)

    assert isinstance(result, AssembledPrompt)
    assert "Recent conversation:" in result.prompt
    assert "User: Hi" in result.prompt
    assert "Assistant: Hello!" in result.prompt


def test_build_prompt_omits_history_section_when_absent():
    candidates = [_chunk(1, "Some fact.", similarity=0.9)]
    result = build_prompt("A question", candidates, history=None, similarity_threshold=0.65)

    assert isinstance(result, AssembledPrompt)
    assert "Recent conversation:" not in result.prompt


def test_build_prompt_only_uses_last_n_history_turns():
    candidates = [_chunk(1, "Some fact.", similarity=0.9)]
    history = [ChatTurn(role="user", content=f"turn-{i}") for i in range(10)]
    result = build_prompt(
        "A question", candidates, history=history, similarity_threshold=0.65, history_turns=3
    )
    assert isinstance(result, AssembledPrompt)
    assert "turn-9" in result.prompt
    assert "turn-7" in result.prompt
    assert "turn-6" not in result.prompt  # older turns should be dropped


# --- Token budget ---


def test_token_budget_keeps_top_chunk_even_if_it_alone_exceeds_budget():
    huge_content = " ".join(f"word{i}" for i in range(1000))
    candidates = [_chunk(1, huge_content, similarity=0.9)]
    result = build_prompt("Q", candidates, similarity_threshold=0.65, max_prompt_tokens=50)

    assert isinstance(result, AssembledPrompt)
    assert len(result.citations) == 1


def test_token_budget_drops_lowest_similarity_tail_chunks():
    # Five candidates, best-first by similarity, each ~100 tokens. A small
    # budget should keep only the first few and drop the (lowest-similarity)
    # tail ones.
    candidates = [
        _chunk(i, " ".join(f"c{i}_w{j}" for j in range(100)), similarity=0.95 - i * 0.05)
        for i in range(5)
    ]
    result = build_prompt("Q", candidates, similarity_threshold=0.65, max_prompt_tokens=250)

    assert isinstance(result, AssembledPrompt)
    kept_markers = [c.marker for c in result.citations]
    # Should keep a strict prefix (best-first order preserved) and drop at
    # least the lowest-similarity candidate.
    assert len(kept_markers) < len(candidates)
    assert kept_markers == list(range(1, len(kept_markers) + 1))


def test_token_budget_generous_keeps_all_chunks():
    candidates = [_chunk(i, f"short content {i}", similarity=0.9 - i * 0.01) for i in range(4)]
    result = build_prompt("Q", candidates, similarity_threshold=0.65, max_prompt_tokens=4000)

    assert isinstance(result, AssembledPrompt)
    assert len(result.citations) == 4
