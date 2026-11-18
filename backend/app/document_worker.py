import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from threading import Timer
from time import monotonic, sleep
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai.embeddings import get_embeddings
from app.ai.vector_store import collection_name, get_vector_store
from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models import subject as _subject, user as _user  # Register document foreign-key targets in standalone workers.
from app.models.document import Document, DocumentStatus as Status
from app.services.document_errors import DocumentError
from app.services.document_storage import get_storage
from app.services.pdf_processor import extract_chunks

logger = logging.getLogger("studybuddy.documents")


@dataclass(frozen=True)
class Job:
    document_id: UUID
    status: Status
    attempt: int
    lease: datetime


def now():
    return datetime.now(timezone.utc)


def claim(db: Session, settings: Settings, *, clock=now) -> Job | None:
    current = clock()
    expired_upload = and_(
        Document.status.in_((Status.PENDING, Status.UPLOADING)),
        Document.created_at <= current - timedelta(hours=settings.upload_expiry_hours),
    )
    due = and_(
        Document.status.in_((Status.UPLOADED, Status.PROCESSING, Status.DELETING)),
        Document.next_attempt_at <= current,
    )
    with db.begin():
        document = db.scalar(
            select(Document).where(Document.storage_provider == "supabase", or_(due, expired_upload))
            .order_by(Document.next_attempt_at.asc().nullsfirst(), Document.created_at)
            .limit(1).with_for_update(skip_locked=True)
        )
        if document is None:
            return None
        if document.status in (Status.PENDING, Status.UPLOADING):
            document.status = Status.DELETING
            document.attempts = 0
        deleting = document.status == Status.DELETING
        if document.attempts >= settings.document_max_attempts:
            fail(document, DocumentError("The document job was interrupted too many times.", retryable=True), settings, clock)
            return None
        if not deleting:
            document.status = Status.PROCESSING
            if document.vector_collection is None:
                document.vector_collection = collection_name(settings)
        document.attempts += 1
        document.next_attempt_at = current + timedelta(seconds=settings.document_job_timeout_seconds + 15)
        return Job(document.id, document.status, document.attempts, document.next_attempt_at)


def fail(document: Document, error: DocumentError, settings: Settings, clock) -> None:
    deleting = document.status == Status.DELETING
    retry_automatically = error.retryable and document.attempts < settings.document_max_attempts
    document.error_message = str(error)
    document.retryable = not retry_automatically and (error.retryable or deleting)
    if not deleting:
        document.status = Status.UPLOADED if retry_automatically else Status.FAILED
        document.page_count = 0
        document.chunk_count = 0
        document.processed_at = None
    document.next_attempt_at = (
        clock() + timedelta(seconds=min(300, 15 * 2 ** max(0, document.attempts - 1)))
        if retry_automatically else None
    )


def process(db: Session, job: Job, settings: Settings, *, clock=now) -> None:
    start = monotonic()
    with db.begin():
        document = db.scalar(select(Document).where(
            Document.id == job.document_id, Document.status == job.status,
            Document.attempts == job.attempt, Document.next_attempt_at == job.lease,
        ).with_for_update())
        if document is None or job.lease <= clock():
            return
        logger.info("document_job stage=%s document_id=%s attempt=%d", job.status, job.document_id, job.attempt)
        try:
            if job.status == Status.DELETING:
                if document.vector_collection:
                    get_vector_store().delete(document.vector_collection, document.user_id, document.id)
                get_storage().delete(document.storage_key)
                db.delete(document)
                outcome = "deleted"
            else:
                ingest(document, settings, clock)
                outcome = "ready"
        except DocumentError as error:
            fail(document, error, settings, clock)
            outcome = document.status.value.lower()
            logger.warning("document_job_failure document_id=%s attempt=%d outcome=%s code=%d retry=%s",
                           job.document_id, job.attempt, outcome, error.status, document.next_attempt_at is not None)
        chunks = document.chunk_count
    logger.info("document_job_complete document_id=%s attempt=%d outcome=%s chunks=%d duration_ms=%d",
                job.document_id, job.attempt, outcome, chunks, (monotonic() - start) * 1000)


def ingest(document: Document, settings: Settings, clock) -> None:
    if document.vector_collection != collection_name(settings):
        raise DocumentError("This document uses an older indexing configuration. Remove it and upload again.")
    if document.checksum is None:
        raise DocumentError("The uploaded PDF was never verified.", 409)
    if document.file_size > settings.max_pdf_size_mb * 1024 * 1024:
        raise DocumentError("The PDF exceeds the current size limit.", 413)
    data = get_storage().download(document.storage_key, document.file_size)
    if len(data) != document.file_size or sha256(data).hexdigest() != document.checksum:
        raise DocumentError("The stored PDF failed its integrity check.", 422)
    logger.info("document_job stage=extract document_id=%s", document.id)
    pages, chunks = extract_chunks(data, document.id, settings)
    embeddings = get_embeddings()
    store = get_vector_store()
    logger.info("document_job stage=embed_index document_id=%s chunks=%d", document.id, len(chunks))
    for start in range(0, len(chunks), settings.embedding_batch_size):
        batch = chunks[start:start + settings.embedding_batch_size]
        vectors = embeddings.embed([chunk.text for chunk in batch])
        store.upsert(document.user_id, document.id, batch, vectors)
    store.verify(document.user_id, document.id, chunks)
    document.page_count = pages
    document.chunk_count = len(chunks)
    document.status = Status.READY
    document.processed_at = clock()
    document.error_message = None
    document.retryable = False
    document.next_attempt_at = None


def on_timeout(job: Job):
    logger.error("document_job_timeout document_id=%s attempt=%d", job.document_id, job.attempt)
    # This process handles one job at a time. The committed lease survives restart.
    os._exit(1)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    logger.info("Document worker started")
    while True:
        job = None
        try:
            with SessionLocal() as db:
                job = claim(db, settings)
                if job is None:
                    sleep(settings.document_poll_seconds)
                    continue
                watchdog = Timer(settings.document_job_timeout_seconds, on_timeout, args=(job,))
                watchdog.daemon = True
                watchdog.start()
                try:
                    process(db, job, settings)
                finally:
                    watchdog.cancel()
        except SQLAlchemyError as error:
            logger.error("document_database_error type=%s", type(error).__name__)
            sleep(settings.document_poll_seconds)
        except Exception as error:
            # Provider exception messages can include private text or request URLs.
            logger.error("document_worker_error document_id=%s type=%s", job.document_id if job else None, type(error).__name__)
            sleep(settings.document_poll_seconds)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
