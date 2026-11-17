"""Hand-written recursive text chunker.

Splits page-tagged document text into overlapping chunks sized for
embedding, using a cascade of separators -- paragraph, then sentence, then a
hard character limit as a last resort -- so we never split more aggressively
than necessary to hit the target chunk size.

Token counts here are approximated by whitespace-delimited word counts. This
is NOT how a real tokenizer (tiktoken, or Gemini's own tokenizer) counts
tokens, but for English prose it's a close enough proxy to size chunks
sensibly without adding a tokenizer dependency. Swap in tiktoken (or a call
to Gemini's count_tokens API) here if exact counts are ever needed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_WORD_RE = re.compile(r"\S+")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
# Split after sentence-ending punctuation, only when followed by whitespace
# and a capital letter/digit/quote -- a cheap heuristic to avoid splitting on
# abbreviations like "Dr." followed by a lowercase word.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")

DEFAULT_TARGET_TOKENS = 500
DEFAULT_OVERLAP_RATIO = 0.15
DEFAULT_HARD_CHAR_LIMIT = 4000  # last-resort split for one run-on "sentence"


def approx_token_count(text: str) -> int:
    """Rough token estimate: whitespace-delimited word count."""
    if not text:
        return 0
    return len(_WORD_RE.findall(text))


@dataclass
class TextChunk:
    page_number: int
    chunk_index: int
    content: str
    token_count: int = 0


@dataclass
class _Unit:
    """An indivisible-ish piece of text tagged with the page it came from."""

    page_number: int
    text: str


def _split_paragraphs(page_number: int, text: str) -> list[_Unit]:
    paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    return [_Unit(page_number, p) for p in paragraphs]


def _split_sentences(unit: _Unit) -> list[_Unit]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(unit.text) if s.strip()]
    if len(sentences) <= 1:
        return [unit]
    return [_Unit(unit.page_number, s) for s in sentences]


def _hard_split(unit: _Unit, hard_char_limit: int) -> list[_Unit]:
    text = unit.text
    if len(text) <= hard_char_limit:
        return [unit]
    pieces: list[_Unit] = []
    for start in range(0, len(text), hard_char_limit):
        piece = text[start : start + hard_char_limit].strip()
        if piece:
            pieces.append(_Unit(unit.page_number, piece))
    return pieces


def _explode_oversized_units(
    units: list[_Unit], target_tokens: int, hard_char_limit: int
) -> list[_Unit]:
    """Recursively cascade any unit larger than target_tokens down through
    paragraph -> sentence -> hard character splitting."""

    def _fits(text: str) -> bool:
        # Token estimate is a whitespace-word count, so a single pathological
        # "word" with no whitespace at all (a long URL/base64 blob, garbled
        # OCR output, ...) would otherwise look like just 1 token and never
        # get split. Guard with an explicit character cap too.
        return approx_token_count(text) <= target_tokens and len(text) <= hard_char_limit

    result: list[_Unit] = []
    for unit in units:
        if _fits(unit.text):
            result.append(unit)
            continue
        sentence_units = _split_sentences(unit)
        if len(sentence_units) == 1:
            # Not splittable into multiple sentences -> hard char split.
            result.extend(_hard_split(unit, hard_char_limit))
            continue
        for su in sentence_units:
            if _fits(su.text):
                result.append(su)
            else:
                result.extend(_hard_split(su, hard_char_limit))
    return result


def _take_overlap_tail(text: str, overlap_tokens: int) -> str:
    if overlap_tokens <= 0:
        return ""
    words = _WORD_RE.findall(text)
    if len(words) <= overlap_tokens:
        return text
    return " ".join(words[-overlap_tokens:])


def chunk_pages(
    pages: Iterable[tuple[int, str]],
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    hard_char_limit: int = DEFAULT_HARD_CHAR_LIMIT,
) -> list[TextChunk]:
    """Chunk page-tagged text into ~target_tokens-sized chunks with overlap.

    `pages` is an iterable of (page_number, page_text) tuples, e.g. as
    yielded by ingestion.parser.extract_pages. Returns a list of TextChunk,
    each retaining the page_number it starts on and a sequential
    chunk_index. Paragraphs (and, when needed, sentences/hard character
    slices) are packed greedily across page boundaries so a chunk's leading
    "overlap" content may come from the previous page.
    """
    overlap_tokens = max(0, round(target_tokens * overlap_ratio))

    units: list[_Unit] = []
    for page_number, page_text in pages:
        if not page_text or not page_text.strip():
            continue
        units.extend(_split_paragraphs(page_number, page_text))

    if not units:
        return []

    units = _explode_oversized_units(units, target_tokens, hard_char_limit)

    chunks: list[TextChunk] = []
    current_units: list[_Unit] = []
    current_tokens = 0
    current_chars = 0
    overlap_prefix = ""

    def flush() -> None:
        nonlocal current_units, current_tokens, current_chars, overlap_prefix
        if not current_units:
            return
        # Attribute the chunk to whichever page contributes the most
        # characters, not just whichever page the first unit happened to
        # come from. Units are packed across page boundaries (see the
        # docstring above), so a chunk can start with a small leftover
        # fragment from the previous page while being mostly the next
        # page's content -- tagging by the first unit alone would mislabel
        # every citation built from it.
        page_char_counts: dict[int, int] = {}
        for u in current_units:
            page_char_counts[u.page_number] = page_char_counts.get(u.page_number, 0) + len(u.text)
        dominant_page = max(page_char_counts, key=page_char_counts.get)
        body = " ".join(u.text for u in current_units)
        content = f"{overlap_prefix} {body}".strip() if overlap_prefix else body
        chunks.append(
            TextChunk(
                page_number=dominant_page,
                chunk_index=len(chunks),
                content=content,
                token_count=approx_token_count(content),
            )
        )
        # Overlap for the *next* chunk is drawn only from this chunk's own
        # new content (not the overlap it inherited), so overlap doesn't
        # compound/grow across many chunks.
        overlap_prefix = _take_overlap_tail(body, overlap_tokens)
        current_units = []
        current_tokens = 0
        current_chars = 0

    for unit in units:
        unit_tokens = approx_token_count(unit.text)
        unit_chars = len(unit.text)
        if current_units and (
            current_tokens + unit_tokens > target_tokens
            # Belt-and-suspenders char cap: keeps a run of low-whitespace
            # units (each individually under target_tokens after hard
            # splitting) from being silently repacked past hard_char_limit.
            or current_chars + unit_chars > hard_char_limit
        ):
            flush()
        current_units.append(unit)
        current_tokens += unit_tokens
        current_chars += unit_chars

    flush()
    return chunks
