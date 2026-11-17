"""Page-level text extraction from raw PDF bytes."""

from __future__ import annotations

import io
from collections.abc import Iterator

from pypdf import PdfReader


def extract_pages(pdf_bytes: bytes) -> Iterator[tuple[int, str]]:
    """Yield (page_number, page_text) tuples for each page in the PDF.
    page_number is 1-indexed. Pages with no extractable text (e.g. a scanned
    image page with no OCR layer) yield an empty string rather than being
    skipped, so page numbering stays accurate for the caller."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        yield (index + 1, text)
