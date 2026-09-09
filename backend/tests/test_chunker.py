"""Unit tests for app.ingestion.chunker: chunk size/overlap behavior,
page_number/chunk_index preservation, and edge cases. Pure logic, no
credentials or DB needed.
"""
from app.ingestion.chunker import approx_token_count, chunk_pages


def _words(prefix: str, n: int) -> str:
    """Build a paragraph of n whitespace-separated, uniquely numbered
    "words" so approx_token_count (a whitespace split) is exact and
    overlap content is easy to assert on."""
    return " ".join(f"{prefix}{i}" for i in range(n))


# --- Edge cases ---


def test_empty_pages_list_returns_no_chunks():
    assert chunk_pages([]) == []


def test_pages_with_only_blank_text_returns_no_chunks():
    assert chunk_pages([(1, ""), (2, "   \n\n  ")]) == []


def test_text_shorter_than_one_chunk_yields_a_single_chunk():
    text = "This is a short paragraph that easily fits in one chunk."
    chunks = chunk_pages([(1, text)], target_tokens=500, overlap_ratio=0.15)

    assert len(chunks) == 1
    assert chunks[0].page_number == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == text


# --- page_number / chunk_index preservation ---


def test_chunk_index_is_sequential_from_zero():
    # Three separate paragraphs, each big enough to force its own chunk.
    pages = [(1, f"{_words('a', 40)}\n\n{_words('b', 40)}\n\n{_words('c', 40)}")]
    chunks = chunk_pages(pages, target_tokens=40, overlap_ratio=0.0)

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len(chunks) >= 2  # sanity: it actually split


def test_page_number_attributed_to_first_page_touched_by_each_chunk():
    # Page 1 has a small paragraph (30 "tokens"); page 2 has a small
    # paragraph (30 "tokens"). With target_tokens=50, they can't both fit
    # in one chunk, so the second paragraph starts a new chunk on page 2.
    page1_text = _words("p1w", 30)
    page2_text = _words("p2w", 30)
    chunks = chunk_pages([(1, page1_text), (2, page2_text)], target_tokens=50, overlap_ratio=0.2)

    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert chunks[1].page_number == 2


# --- Overlap behavior ---


def test_overlap_carries_tail_of_previous_chunk_into_next():
    # Paragraph A (30 tokens) then paragraph B (30 tokens); target=50 tokens
    # forces a split after A. overlap_ratio=0.2 -> 10 overlap tokens.
    para_a = _words("w", 30)  # w0..w29
    para_b = _words("v", 30)  # v0..v29
    chunks = chunk_pages([(1, f"{para_a}\n\n{para_b}")], target_tokens=50, overlap_ratio=0.2)

    assert len(chunks) == 2
    tail_of_a = para_a.split()[-10:]
    head_of_chunk2 = chunks[1].content.split()[:10]
    assert head_of_chunk2 == tail_of_a
    # And the new content (paragraph B) is still fully present.
    assert "v0" in chunks[1].content and "v29" in chunks[1].content


def test_zero_overlap_means_no_shared_tokens_between_chunks():
    para_a = _words("w", 30)
    para_b = _words("v", 30)
    chunks = chunk_pages([(1, f"{para_a}\n\n{para_b}")], target_tokens=50, overlap_ratio=0.0)

    assert len(chunks) == 2
    assert chunks[1].content.split()[0] == "v0"


def test_approx_token_count_counts_whitespace_separated_words():
    assert approx_token_count("") == 0
    assert approx_token_count("one two three") == 3
    assert approx_token_count("  extra   spaces   here  ") == 3


# --- Oversized-unit cascade (paragraph -> sentence -> hard char limit) ---


def test_oversized_paragraph_is_split_by_sentence():
    # A single "paragraph" (no blank-line breaks) made of many short
    # sentences, too big to fit target_tokens as one unit.
    sentences = " ".join(f"Sentence number {i} is here." for i in range(40))
    chunks = chunk_pages([(1, sentences)], target_tokens=30, overlap_ratio=0.0)

    assert len(chunks) > 1
    for c in chunks:
        # Each produced chunk should be reasonably close to the target
        # (allowing some slack since packing is greedy over whole sentences).
        assert c.token_count <= 30 + 10


def test_hard_char_limit_splits_a_single_unsplittable_run_on_string():
    # No sentence punctuation at all -> falls through to hard char split.
    run_on = "x" * 9000
    chunks = chunk_pages([(1, run_on)], target_tokens=50, hard_char_limit=4000, overlap_ratio=0.0)

    assert len(chunks) >= 2
    for c in chunks:
        assert len(c.content) <= 4000
