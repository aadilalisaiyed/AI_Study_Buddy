from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID, uuid5

import pymupdf
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import Settings
from app.services.document_errors import DocumentError

PIPELINE_VERSION = "pdf-v1"


@dataclass(frozen=True)
class Chunk:
    id: str
    page: int
    index: int
    text: str
    checksum: str


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")


def extract_chunks(data: bytes, document_id: UUID, settings: Settings) -> tuple[int, list[Chunk]]:
    if len(data) < 5 or data[:5] != b"%PDF-":
        raise DocumentError("This file is not a PDF.", 415)
    if len(data) > settings.max_pdf_size_mb * 1024 * 1024:
        raise DocumentError("The PDF exceeds the upload size limit.", 413)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.pdf_chunk_size,
        chunk_overlap=settings.pdf_chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
        strip_whitespace=False,
    )
    chunks = []
    character_count = 0
    try:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            if pdf.needs_pass or pdf.is_encrypted or (pdf.metadata or {}).get("encryption"):
                raise DocumentError("Password-protected or encrypted PDFs are unsupported.", 422)
            if pdf.is_repaired or not pdf.is_pdf or pdf.page_count < 1:
                raise DocumentError("The PDF is empty or damaged. Export a fresh PDF and try again.", 422)
            if pdf.page_count > settings.max_pdf_pages:
                raise DocumentError(f"The PDF exceeds the {settings.max_pdf_pages}-page limit.", 422)
            for number, page in enumerate(pdf, 1):
                text = normalize_text(page.get_text("text", sort=True))
                character_count += len(text)
                if character_count > settings.max_pdf_text_chars:
                    raise DocumentError("The PDF has too much extracted text. Split it into smaller files.", 422)
                for index, content in enumerate(splitter.split_text(text)):
                    if not content.strip():
                        continue
                    checksum = sha256(content.encode()).hexdigest()
                    chunk_id = str(uuid5(document_id, f"{PIPELINE_VERSION}:{number}:{index}:{checksum}"))
                    chunks.append(Chunk(chunk_id, number, index, content, checksum))
                    if len(chunks) > settings.max_pdf_chunks:
                        raise DocumentError("The PDF would create too many chunks. Split it into smaller files.", 422)
            if not chunks:
                raise DocumentError("No selectable text was found. Run OCR on the scanned pages and upload a text PDF.", 422)
            return pdf.page_count, chunks
    except (pymupdf.FileDataError, RuntimeError, ValueError, TypeError) as error:
        raise DocumentError("The PDF could not be parsed. Export a fresh PDF and try again.", 422) from error
