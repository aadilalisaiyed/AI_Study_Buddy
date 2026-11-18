from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.embeddings import get_embeddings
from app.ai.vector_store import collection_name, get_vector_store
from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.services.document_errors import DocumentError


@dataclass(frozen=True)
class RetrievedChunk:
    document_id: UUID
    filename: str
    page_number: int
    text: str
    distance: float
    reference: str


def retrieve(
    db: Session, *, owner_id: UUID, query: str, document_ids: list[UUID] | None = None, top_k: int = 5,
) -> list[RetrievedChunk]:
    """Retrieve chunks for an owner ID supplied by trusted authentication code."""
    query = query.strip()
    if not 1 <= top_k <= 30 or not 1 <= len(query) <= 2000 or (document_ids is not None and len(document_ids) > 100):
        raise DocumentError("Invalid retrieval query, document scope, or result count.", 422)
    ids = set(document_ids) if document_ids is not None else None
    if ids is not None:
        owned = set(db.scalars(select(Document.id).where(
            Document.user_id == owner_id, Document.id.in_(ids), Document.status != DocumentStatus.DELETING,
        )))
        if ids != owned:
            raise DocumentError("Document not found.", 404)
    filters = [
        Document.user_id == owner_id, Document.status == DocumentStatus.READY,
        Document.vector_collection == collection_name(get_settings()),
    ]
    if ids is not None:
        filters.append(Document.id.in_(ids))
    documents = dict(db.execute(select(Document.id, Document.filename).where(*filters)).all())
    if not documents:
        return []
    store = get_vector_store()
    result = store.query(owner_id, list(documents), get_embeddings().embed([query], query=True)[0], top_k)
    if result is None:
        return []
    # A document may have entered deletion while the external query was in flight.
    current = dict(db.execute(select(Document.id, Document.filename).where(*filters, Document.id.in_(documents))).all())
    chunks = []
    for reference, metadata, text, distance in zip(
        result["ids"][0], result["metadatas"][0], result["documents"][0], result["distances"][0], strict=True,
    ):
        if metadata["owner_id"] != str(owner_id):
            continue
        document_id = UUID(metadata["document_id"])
        if document_id in current:
            chunks.append(RetrievedChunk(document_id, current[document_id], metadata["page"], text, distance, reference))
    return chunks
