"""Page-level text extraction from raw PDF bytes."""

from __future__ import annotations

import io
import re
import zipfile
from collections.abc import Iterator
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

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


# ---------------------------------------------------------------------------
# Non-PDF formats. Standard library only (no extra dependencies to audit).
# These formats have no real pages, so text is returned as page 1, except DOCX
# where explicit page breaks advance the page number.
# ---------------------------------------------------------------------------

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm")
MAX_DOCX_UNCOMPRESSED = 50 * 1024 * 1024  # zip-bomb guard

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def is_supported(filename: str) -> bool:
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        return data.decode("latin-1")


class _TextHTML(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "head"}
    _BLOCK = {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(raw: str) -> str:
    p = _TextHTML()
    p.feed(raw)
    text = "".join(p.parts)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", text)).strip()


def _docx_pages(data: bytes) -> list[tuple[int, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        info = zf.getinfo("word/document.xml")
        if info.file_size > MAX_DOCX_UNCOMPRESSED:
            raise ValueError("DOCX content too large")
        root = ET.fromstring(zf.read("word/document.xml"))
    pages: list[list[str]] = [[]]
    for para in root.iter(f"{_W}p"):
        buf: list[str] = []
        for el in para.iter():
            if el.tag == f"{_W}t" and el.text:
                buf.append(el.text)
            elif el.tag == f"{_W}tab":
                buf.append("\t")
            elif el.tag == f"{_W}br" and el.get(f"{_W}type") == "page":
                pages[-1].append("".join(buf))
                buf = []
                pages.append([])
        pages[-1].append("".join(buf))
    return [(i + 1, "\n".join(p)) for i, p in enumerate(pages)]


def extract_document_pages(filename: str, data: bytes) -> list[tuple[int, str]]:
    """Dispatch on file extension. Returns [(page_number, text)]."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return list(extract_pages(data))
    if name.endswith(".docx"):
        return _docx_pages(data)
    text = _decode(data)
    if name.endswith((".html", ".htm")):
        text = _html_to_text(text)
    return [(1, text)]
