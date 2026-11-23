import io
import zipfile

import pytest

from app.ingestion.parser import extract_document_pages, is_supported

DOCX_XML = (
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t> world</w:t></w:r></w:p>"
    '<w:p><w:r><w:br w:type="page"/></w:r><w:r><w:t>Second page</w:t></w:r></w:p>'
    "</w:body></w:document>"
)


def _docx(xml: str = DOCX_XML) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_supported_extensions():
    assert all(is_supported(f) for f in ["a.PDF", "b.docx", "c.md", "d.txt", "e.html", "f.htm"])
    assert not is_supported("x.exe")


def test_docx_pages_and_text():
    pages = extract_document_pages("a.docx", _docx())
    assert pages[0] == (1, "Hello world\n")
    assert pages[1][0] == 2 and "Second page" in pages[1][1]


def test_html_strips_scripts_and_tags():
    html = b"<html><head><title>t</title></head><body><script>evil()</script><p>Hi <b>there</b></p><p>Bye</p></body></html>"
    ((page, text),) = extract_document_pages("a.html", html)
    assert page == 1 and "evil" not in text and "Hi there" in text and "Bye" in text


def test_markdown_and_txt_decode_with_bom_and_latin1():
    assert extract_document_pages("a.md", b"\xef\xbb\xbf# T")[0][1] == "# T"
    assert extract_document_pages("a.txt", "café".encode("latin-1"))[0][1] == "café"


def test_corrupt_docx_raises():
    with pytest.raises(zipfile.BadZipFile):
        extract_document_pages("a.docx", b"not a zip")
