import asyncio
from datetime import datetime, timezone
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import Annotated, BinaryIO, Literal
from unicodedata import category, normalize
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.document import Document, DocumentStatus as Status
from app.models.user import User
from app.schemas.document import DocumentList, DocumentResponse, UploadInit, UploadInstructions
from app.services.document_errors import DocumentError
from app.services.document_storage import PDF_MIME, get_storage
from app.services.storage.supabase_storage import SupabaseStorage

router = APIRouter(prefix="/api/v1/documents", tags=["Documents"])
DB = Annotated[Session, Depends(get_db)]
Owner = Annotated[User, Depends(get_current_user)]
UPLOAD_STATES = (Status.PENDING, Status.UPLOADING)
ACTIVE_STATES = (Status.UPLOADED, Status.PROCESSING, Status.READY)


def storage() -> SupabaseStorage:
    try:
        return get_storage()
    except DocumentError as error:
        raise HTTPException(error.status, str(error)) from error


def owned(db: Session, user_id: UUID, document_id: UUID, *, lock: bool = False) -> Document:
    query = select(Document).where(Document.id == document_id, Document.user_id == user_id)
    query = query.execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update(nowait=True)
    try:
        document = db.scalar(query)
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) == "55P03":
            db.rollback()
            raise HTTPException(409, "This document is busy. Try again shortly.") from error
        raise
    if document is None:
        raise HTTPException(404, "Document not found.")
    return document


def ensure_supabase(document: Document) -> None:
    if document.storage_provider != "supabase":
        raise HTTPException(409, "This PDF is in legacy storage. Re-upload the original to use Supabase.")


def sanitized_filename(raw: str) -> str:
    name = normalize("NFC", raw).replace(chr(92), "/").split("/")[-1]
    name = "".join(char for char in name if not category(char).startswith("C")).strip(" .")
    if not name.lower().endswith(".pdf") or not name[:-4].strip(" ."):
        raise HTTPException(415, "Choose a PDF file.")
    return name[:-4][:236] + ".pdf"


def persist(db: Session, document: Document) -> DocumentResponse:
    db.flush()
    result = DocumentResponse.model_validate(document)
    db.commit()
    return result


@router.post("/uploads/init", status_code=201, response_model=UploadInstructions)
def init_upload(data: UploadInit, owner: Owner, db: DB):
    filename = sanitized_filename(data.filename)
    if data.content_type != PDF_MIME:
        raise HTTPException(415, "Only application/pdf is supported.")
    if data.file_size > get_settings().max_pdf_size_mb * 1024 * 1024:
        raise HTTPException(413, f"PDFs must be at most {get_settings().max_pdf_size_mb} MB.")
    settings = get_settings()
    # Serialize reservations across users, including pending uploads and unfinished deletions.
    db.execute(text("SELECT pg_advisory_xact_lock(7142095032)"))
    owned_count = db.scalar(select(func.count()).select_from(Document).where(Document.user_id == owner.id))
    if owned_count >= settings.max_documents_per_user:
        raise HTTPException(429, "Your document limit has been reached. Remove a document before uploading another.")
    reserved_size = db.scalar(select(func.coalesce(func.sum(Document.file_size), 0)).where(
        Document.storage_provider == "supabase",
    ))
    if reserved_size + data.file_size > settings.total_document_storage_mb * 1024 * 1024:
        raise HTTPException(429, "The application's storage quota is full. Try again after files are removed.")
    document_id = uuid4()
    document = Document(
        id=document_id, user_id=owner.id, filename=filename,
        storage_key=f"users/{owner.id}/documents/{document_id}/original.pdf",
        content_type=PDF_MIME, file_size=data.file_size, status=Status.PENDING, storage_provider="supabase",
    )
    db.add(document)
    prefix = f"{router.prefix}/{document_id}/uploads"
    return UploadInstructions(document=persist(db, document), upload_path=f"{prefix}/content", complete_path=f"{prefix}/complete")


def store_pdf(db: Session, owner_id: UUID, document_id: UUID, source: BinaryIO, size: int, digest: str) -> DocumentResponse:
    document = owned(db, owner_id, document_id, lock=True)
    if document.status not in UPLOAD_STATES:
        raise HTTPException(409, "This document no longer accepts uploads.")
    ensure_supabase(document)
    if document.checksum is not None and document.checksum != digest:
        raise HTTPException(409, "Resume with the original PDF or start a new upload.")
    if size != document.file_size:
        raise HTTPException(400, "The uploaded PDF size does not match the selected file.")
    if document.checksum is None:
        document.checksum = digest
        db.commit()
        document = owned(db, owner_id, document_id, lock=True)
        if document.status not in UPLOAD_STATES:
            raise HTTPException(409, "This document no longer accepts uploads.")
    try:
        adapter = storage()
        adapter.ensure_private()
        adapter.upload(document.storage_key, source, size, digest)
    except DocumentError as error:
        raise HTTPException(error.status, str(error)) from error
    document.status = Status.UPLOADING
    return persist(db, document)


@router.put("/{document_id}/uploads/content", response_model=DocumentResponse)
async def upload_content(document_id: UUID, request: Request, owner: Owner, db: DB):
    owner_id = owner.id
    document = await run_in_threadpool(owned, db, owner_id, document_id)
    if document.status not in UPLOAD_STATES:
        raise HTTPException(409, "This document no longer accepts uploads.")
    if request.headers.get("content-type") != PDF_MIME:
        raise HTTPException(415, "Send the PDF using application/pdf.")
    ensure_supabase(document)
    expected = document.file_size
    limit = get_settings().max_pdf_size_mb * 1024 * 1024
    await run_in_threadpool(db.rollback)
    if expected > limit:
        raise HTTPException(413, "The PDF is above the current upload limit.")
    declared = request.headers.get("content-length")
    if declared is not None and (not declared.isascii() or not declared.isdecimal() or declared != str(expected)):
        raise HTTPException(400, "The uploaded PDF size does not match the selected file.")
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as source:
        digest = sha256()
        size = 0
        try:
            async with asyncio.timeout(90):
                async for piece in request.stream():
                    size += len(piece)
                    if size > limit:
                        raise HTTPException(413, "The PDF is above the upload limit.")
                    if size > expected:
                        raise HTTPException(400, "The uploaded PDF size does not match the selected file.")
                    digest.update(piece)
                    await run_in_threadpool(source.write, piece)
        except (TimeoutError, ClientDisconnect) as error:
            raise HTTPException(400, "The upload was interrupted. Try again.") from error
        if size != expected:
            raise HTTPException(400, "The upload ended before the entire PDF arrived.")
        source.seek(0)
        if source.read(5) != b"%PDF-":
            raise HTTPException(415, "The file does not contain a PDF header.")
        return await run_in_threadpool(store_pdf, db, owner_id, document_id, source, size, digest.hexdigest())


@router.post("/{document_id}/uploads/complete", status_code=202, response_model=DocumentResponse)
def complete_upload(document_id: UUID, owner: Owner, db: DB):
    document = owned(db, owner.id, document_id)
    ensure_supabase(document)
    if document.status in ACTIVE_STATES or (document.status == Status.FAILED and document.checksum):
        return DocumentResponse.model_validate(document)
    document = owned(db, owner.id, document_id, lock=True)
    if document.status in ACTIVE_STATES or (document.status == Status.FAILED and document.checksum):
        return DocumentResponse.model_validate(document)
    if document.status not in UPLOAD_STATES:
        raise HTTPException(409, "This upload can no longer be completed.")
    if not document.checksum:
        raise HTTPException(409, "The PDF has not reached storage. Upload it first.")
    try:
        actual = storage().download(document.storage_key, document.file_size)
    except DocumentError as error:
        if error.status == 404:
            raise HTTPException(409, "The PDF has not reached storage. Resume the upload.") from error
        raise HTTPException(error.status, str(error)) from error
    if len(actual) != document.file_size or not actual.startswith(b"%PDF-") or sha256(actual).hexdigest() != document.checksum:
        raise HTTPException(422, "The stored PDF could not be verified. Remove it and upload again.")
    document.status = Status.UPLOADED
    document.next_attempt_at = datetime.now(timezone.utc)
    return persist(db, document)


@router.get("", response_model=DocumentList)
def list_documents(
    owner: Owner, db: DB, page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
    search: Annotated[str, Query(max_length=240)] = "",
    status: Status | None = None, subject_id: UUID | None = None, sort: Literal["newest", "oldest"] = "newest",
):
    filters = [Document.user_id == owner.id]
    if subject_id is not None:
        filters.append(Document.subject_id == subject_id)
    if search.strip():
        filters.append(Document.filename.icontains(search.strip(), autoescape=True))
    if status is not None:
        filters.append(Document.status == status)
    ordering = (Document.created_at.desc(), Document.id.desc()) if sort == "newest" else (Document.created_at, Document.id)
    total = db.scalar(select(func.count()).select_from(Document).where(*filters))
    items = db.scalars(select(Document).where(*filters).order_by(*ordering).offset((page - 1) * page_size).limit(page_size)).all()
    return DocumentList(items=[DocumentResponse.model_validate(item) for item in items], page=page, page_size=page_size, total=total)


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(document_id: UUID, owner: Owner, db: DB):
    return DocumentResponse.model_validate(owned(db, owner.id, document_id))


@router.get("/{document_id}/download", response_class=Response, responses={200: {"content": {PDF_MIME: {}}}})
def download(document_id: UUID, owner: Owner, db: DB):
    document = owned(db, owner.id, document_id)
    ensure_supabase(document)
    if document.status in (*UPLOAD_STATES, Status.DELETING) or not document.checksum:
        raise HTTPException(409, "This original PDF is not available.")
    try:
        data = storage().download(document.storage_key, document.file_size)
    except DocumentError as error:
        raise HTTPException(error.status, str(error)) from error
    if len(data) != document.file_size or sha256(data).hexdigest() != document.checksum:
        raise HTTPException(409, "The stored PDF failed its integrity check.")
    document = owned(db, owner.id, document_id)
    if document.status == Status.DELETING:
        raise HTTPException(409, "This PDF is being removed.")
    return Response(data, media_type=PDF_MIME, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(document.filename, safe='')}",
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.post("/{document_id}/retry", status_code=202, response_model=DocumentResponse)
def retry(document_id: UUID, owner: Owner, db: DB):
    document = owned(db, owner.id, document_id, lock=True)
    ensure_supabase(document)
    if document.status in (Status.UPLOADED, Status.PROCESSING):
        return DocumentResponse.model_validate(document)
    if document.status != Status.FAILED or not document.retryable or not document.checksum:
        raise HTTPException(409, "Processing cannot be retried for this document.")
    document.status = Status.UPLOADED
    document.attempts = 0
    document.error_message = None
    document.retryable = False
    document.next_attempt_at = datetime.now(timezone.utc)
    return persist(db, document)


@router.delete("/{document_id}", status_code=202, response_model=DocumentResponse)
def request_deletion(document_id: UUID, owner: Owner, db: DB):
    document = owned(db, owner.id, document_id, lock=True)
    ensure_supabase(document)
    if document.status == Status.DELETING and document.next_attempt_at is not None:
        return DocumentResponse.model_validate(document)
    document.status = Status.DELETING
    document.attempts = 0
    document.error_message = None
    document.retryable = False
    document.next_attempt_at = datetime.now(timezone.utc)
    return persist(db, document)
