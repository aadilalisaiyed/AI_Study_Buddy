from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.ai.llm import TutorError
from app.ai.rag_service import RAGAnswer, answer_question
from app.core.config import get_settings
from app.api.documents import DB, Owner
from app.models.conversation import Conversation, Message
from app.schemas.chat import (
    ConversationCreate, ConversationDetail, ConversationList, ConversationUpdate, ConversationView,
    MessageList, MessageView, Question,
)
from app.services.conversation_service import (
    admit_question, conversation, format_messages, now, replace_documents, selected_documents, validate_documents,
)
from app.services.document_errors import DocumentError

router = APIRouter(prefix="/api/v1/chat/conversations", tags=["AI Tutor"])


def tutor_error(_, error: TutorError):
    return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=error.status)


def detail(db: DB, item: Conversation) -> ConversationDetail:
    return ConversationDetail(
        **ConversationView.model_validate(item).model_dump(),
        document_ids=selected_documents(db, item.id),
    )


@router.post("", status_code=201, response_model=ConversationDetail)
def create(data: ConversationCreate, owner: Owner, db: DB):
    docs = validate_documents(db, owner.id, data.document_ids, get_settings(), lock=True)
    item = Conversation(user_id=owner.id, title=data.title)
    db.add(item)
    db.flush()
    replace_documents(db, item.id, docs)
    db.flush()
    result = detail(db, item)
    db.commit()
    return result


@router.get("", response_model=ConversationList)
def list_conversations(
    owner: Owner, db: DB, limit: Annotated[int, Query(ge=1, le=40)] = 20,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
):
    rows = db.scalars(select(Conversation).where(Conversation.user_id == owner.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(offset).limit(limit + 1)).all()
    return ConversationList(items=[ConversationView.model_validate(row) for row in rows[:limit]], has_more=len(rows) > limit, max_documents=get_settings().chat_max_documents)


@router.get("/{identifier}", response_model=ConversationDetail)
def get_conversation(identifier: UUID, owner: Owner, db: DB):
    return detail(db, conversation(db, owner.id, identifier))


@router.patch("/{identifier}", response_model=ConversationDetail)
def update_conversation(identifier: UUID, data: ConversationUpdate, owner: Owner, db: DB):
    item = conversation(db, owner.id, identifier, lock=True)
    if data.document_ids is not None:
        docs = validate_documents(db, owner.id, data.document_ids, get_settings(), lock=True)
        replace_documents(db, item.id, docs)
    if data.title is not None:
        item.title = data.title
    item.updated_at = now()
    db.flush()
    result = detail(db, item)
    db.commit()
    return result


@router.delete("/{identifier}", status_code=204)
def delete_conversation(identifier: UUID, owner: Owner, db: DB):
    item = conversation(db, owner.id, identifier, lock=True)
    if db.scalar(select(Message.id).where(
        Message.conversation_id == identifier, Message.status == "pending", Message.expires_at > now(),
    ).limit(1)):
        raise TutorError("chat_busy", "Wait for the in-progress answer before deleting this conversation.", 409)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/{identifier}/messages", response_model=MessageList)
def list_messages(
    identifier: UUID, owner: Owner, db: DB,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 24,
):
    conversation(db, owner.id, identifier)
    filters = [Message.conversation_id == identifier]
    if before is not None:
        filters.append(Message.ordinal < before)
    rows = db.scalars(select(Message).where(*filters).order_by(Message.ordinal.desc()).limit(limit + 1)).all()
    return MessageList(
        items=format_messages(db, owner.id, list(reversed(rows[:limit]))),
        next_before=rows[limit - 1].ordinal if len(rows) > limit else None,
    )


@router.post("/{identifier}/messages", response_model=list[MessageView])
def submit(identifier: UUID, data: Question, owner: Owner, db: DB):
    owner_id = owner.id
    current, job = admit_question(db, owner_id, identifier, data)
    if job is None:
        return current
    assistant_id, documents, history = job
    settings = get_settings()
    failure = None
    answer = None
    try:
        answer = answer_question(db, owner_id=owner_id, documents=documents, question=data.content,
                                 history=history, settings=settings)
    except TutorError as error:
        failure = error
    except DocumentError as error:
        failure = TutorError("provider_configuration", str(error), error.status)
    db.rollback()
    conversation(db, owner_id, identifier, lock=True)
    assistant = db.scalar(select(Message).where(Message.id == assistant_id).with_for_update())
    if assistant.status != "pending" or assistant.expires_at <= now():
        raise TutorError("generation_timeout", "The answer did not finish before its deadline. Try again.", 504)
    if failure is None:
        try:
            validate_documents(db, owner_id, documents, settings, lock=True)
        except TutorError as error:
            failure = error
    assistant.expires_at = None
    if failure is not None:
        assistant.status = "failed"
        assistant.error_code = failure.code
        db.commit()
        raise failure
    assert isinstance(answer, RAGAnswer)
    assistant.status = "completed"
    assistant.content = answer.content
    assistant.citations = [source.model_dump(mode="json") for source in answer.citations]
    assistant.model = answer.model
    assistant.token_usage = answer.usage
    db.flush()
    messages = db.scalars(select(Message).where(
        Message.conversation_id == identifier, Message.request_id == data.request_id,
    ).order_by(Message.ordinal)).all()
    result = format_messages(db, owner_id, list(messages))
    db.commit()
    return result
