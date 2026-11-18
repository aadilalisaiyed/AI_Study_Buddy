from uuid import uuid4

import pymupdf
import pytest

from app.core.config import Settings
from app.services.document_errors import DocumentError
from app.services.pdf_processor import extract_chunks


def make_pdf(*pages: str, encrypted=False):
    with pymupdf.open() as pdf:
        for text in pages:
            page = pdf.new_page()
            if text:
                page.insert_textbox(pymupdf.Rect(36, 36, 550, 780), text, fontsize=10)
        options = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256, "user_pw": "private-password", "owner_pw": "owner-password",
        } if encrypted else {}
        return pdf.tobytes(**options)


def test_real_pdf_chunking_keeps_pages_and_content():
    settings = Settings(pdf_chunk_size=100, pdf_chunk_overlap=25)
    lines = ["Topic " + str(index) + " explains dependency analysis." for index in range(8)]
    data = make_pdf("\n".join(lines), "Second page: normalization removes redundancy.")
    document = uuid4()
    pages, chunks = extract_chunks(data, document, settings)
    assert pages == 2
    assert {chunk.page for chunk in chunks} == {1, 2}
    assert all(0 < len(chunk.text) <= 100 for chunk in chunks)
    assert all(any(line in chunk.text for chunk in chunks if chunk.page == 1) for line in lines)
    first_page = [chunk.text for chunk in chunks if chunk.page == 1]
    assert any(first[-12:] in second for first, second in zip(first_page, first_page[1:]))
    assert "normalization" in chunks[-1].text
    assert extract_chunks(data, document, settings)[1] == chunks
    assert {chunk.id for chunk in extract_chunks(data, uuid4(), settings)[1]}.isdisjoint(chunk.id for chunk in chunks)


@pytest.mark.parametrize(("data", "match"), [
    (b"", "not a PDF"),
    (b"%PDF-1.7\ncorrupt", "could not be parsed"),
    (make_pdf(""), "OCR"),
    (make_pdf("Private reading material", encrypted=True), "encrypted"),
])
def test_invalid_pdf(data, match):
    with pytest.raises(DocumentError, match=match) as failure:
        extract_chunks(data, uuid4(), Settings())
    assert not failure.value.retryable


def test_image_only_pdf_needs_ocr():
    with pymupdf.open() as pdf:
        rect = pymupdf.IRect(0, 0, 2, 2)
        pixels = pymupdf.Pixmap(pymupdf.csRGB, rect, False)
        pixels.clear_with(127)
        pdf.new_page().insert_image(pymupdf.Rect(36, 36, 100, 100), pixmap=pixels)
        data = pdf.tobytes()
    with pytest.raises(DocumentError, match="OCR"):
        extract_chunks(data, uuid4(), Settings())


@pytest.mark.parametrize(("options", "match"), [
    ({"max_pdf_pages": 1}, "page limit"),
    ({"max_pdf_chunks": 1}, "too many chunks"),
])
def test_resource_limits(options, match):
    with pytest.raises(DocumentError, match=match):
        extract_chunks(make_pdf("First topic", "Second topic"), uuid4(), Settings(**options))
