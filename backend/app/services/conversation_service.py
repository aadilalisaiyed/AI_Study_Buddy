from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.ai.llm import TutorError
from app.ai.vector_store import collection_name
from app.core.config import Settings, get_settings
from app.models.conversation import ChatUsage, Conversation, ConversationDocument, Message
from app.models.document import Document, DocumentStatus
from app.services.ai_admission import require_free_slot, serialize_generation
from app.schemas.chat import Citation, MessageView, Question

TERMINAL_DEADLINE = timedelta(minutes=4)


def now():
    return datetime.now(timezone.utc)


def conversation(db: Session, owner: UUID, identifier: UUID, *, lock=False) -> Conversation:
    query = select(Conversation).where(Conversation.id == identifier, Conversation.user_id == owner)
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise TutorError("conversation_not_found", "Conversation not found.", 404)
    return item


def validate_documents(db: Session, owner: UUID, identifiers: list[UUID], settings: Settings, *, lock: bool = False, max_documents: int | None = None) -> list[UUID]:
    ids = list(dict.fromkeys(identifiers))
    limit = max_documents or settings.chat_max_documents
    if len(ids) > limit:
        raise TutorError("too_many_documents", f"Select at most {limit} documents.", 422)
    query = select(Document.id, Document.status, Document.vector_collection).where(
        Document.user_id == owner, Document.id.in_(ids),
    ).order_by(Document.id)
    rows = db.execute(query.with_for_update(read=True) if lock else query).all()
    if len(rows) != len(ids):
        raise TutorError("document_not_found", "Document not found.", 404)
    if any(row.status != DocumentStatus.READY or row.vector_collection != collection_name(settings) for row in rows):
        raise TutorError("document_unavailable", "Select PDFs that are ready on the current index.", 409)
    return ids


def selected_documents(db: Session, identifier: UUID) -> list[UUID]:
    return list(db.scalars(select(ConversationDocument.document_id).where(
        ConversationDocument.conversation_id == identifier,
    ).order_by(ConversationDocument.document_id)))


def replace_documents(db: Session, identifier: UUID, ids: list[UUID]) -> None:
    db.execute(delete(ConversationDocument).where(ConversationDocument.conversation_id == identifier))
    db.add_all(ConversationDocument(conversation_id=identifier, document_id=document_id) for document_id in ids)


def format_messages(db: Session, owner: UUID, messages: list[Message]) -> list[MessageView]:
    citation_ids = {UUID(source["document_id"]) for message in messages for source in message.citations}
    available = set(db.scalars(select(Document.id).where(
        Document.id.in_(citation_ids), Document.user_id == owner, Document.status == DocumentStatus.READY,
        Document.storage_provider == "supabase",
    ))) if citation_ids else set()
    views = []
    for message in messages:
        status, error = message.status, message.error_code
        if status == "pending" and message.expires_at <= now():
            status, error = "failed", "generation_timeout"
        citations = []
        for item in message.citations:
            source = Citation.model_validate(item)
            if source.document_id not in available:
                source = source.model_copy(update={"available": False, "excerpt": None, "chunk_id": None})
            citations.append(source)
        views.append(MessageView(
            id=message.id, request_id=message.request_id, ordinal=message.ordinal,
            role=message.role, status=status, content=message.content, created_at=message.created_at,
            citations=citations, error_code=error,
        ))
    return views


def admit_question(db: Session, owner: UUID, identifier: UUID, data: Question):
    settings = get_settings()
    current = now()
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"), {"scope": f"study-chat:{owner}"})
    serialize_generation(db)
    item = conversation(db, owner, identifier, lock=True)
    existing = db.scalars(select(Message).where(
        Message.conversation_id == identifier, Message.request_id == data.request_id,
    ).order_by(Message.ordinal)).all()
    if existing:
        if existing[0].content != data.content or set(existing[0].document_ids) != {str(item) for item in data.document_ids}:
            raise TutorError("request_conflict", "This request identifier was already used.", 409)
        return format_messages(db, owner, list(existing)), None

    require_free_slot(db, current)
    documents = validate_documents(db, owner, data.document_ids, settings, lock=True)
    scope = select(Conversation.id).where(Conversation.user_id == owner)
    db.execute(update(Message).where(
        Message.conversation_id.in_(scope), Message.status == "pending", Message.expires_at <= current,
    ).values(status="failed", error_code="generation_timeout", expires_at=None))
    pending = list(db.scalars(select(Message.conversation_id).where(
        Message.conversation_id.in_(scope), Message.status == "pending",
    )))
    if identifier in pending or len(pending) >= settings.chat_max_concurrent:
        raise TutorError("chat_busy", "An answer is already in progress. Wait before sending another question.", 429)

    today = current - timedelta(days=1)
    minute = current - timedelta(minutes=1)
    db.execute(delete(ChatUsage).where(ChatUsage.user_id == owner, ChatUsage.created_at < today))
    day_count, minute_count = db.execute(select(
        func.count(ChatUsage.id), func.count(ChatUsage.id).filter(ChatUsage.created_at >= minute),
    ).where(ChatUsage.user_id == owner)).one()
    if day_count >= settings.chat_requests_per_day or minute_count >= settings.chat_requests_per_minute:
        raise TutorError("rate_limit", "Your tutor request limit has been reached. Try again later.", 429)

    ids = [str(value) for value in documents]
    history_rows = db.scalars(select(Message).where(
        Message.conversation_id == identifier, Message.status == "completed",
    ).order_by(Message.ordinal.desc()).limit(settings.chat_history_messages * 3)).all()
    # A prior answer may clarify intent only when its entire source scope is still selected.
    history = [{"role": row.role, "text": row.content[:600]} for row in history_rows
               if row.document_ids and set(row.document_ids).issubset(ids)]
    history = list(reversed(history[:settings.chat_history_messages]))
    replace_documents(db, identifier, documents)
    if item.title == "New conversation" and item.last_message_at is None:
        item.title = " ".join(data.content.split())[:100]
    item.last_message_at = current
    question = Message(conversation_id=identifier, request_id=data.request_id, role="user",
                       status="completed", content=data.content, document_ids=ids)
    db.add(question)
    db.flush()
    pending_message = Message(conversation_id=identifier, request_id=data.request_id, role="assistant",
                              status="pending", expires_at=current + TERMINAL_DEADLINE, document_ids=ids)
    db.add_all([pending_message, ChatUsage(user_id=owner)])
    db.flush()
    assistant_id = pending_message.id
    db.commit()
    return None, (assistant_id, documents, history)
