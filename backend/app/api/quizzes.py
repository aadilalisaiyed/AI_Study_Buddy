from datetime import timedelta
from hashlib import sha256
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, select

from app.ai import quiz_generator
from app.ai.llm import TutorError
from app.api.documents import DB, Owner
from app.core.config import get_settings
from app.models.document import Document, DocumentStatus
from app.models.quiz import Quiz, QuizAnswer, QuizAttempt, QuizQuestion, QuizUsage
from app.schemas.quiz import AttemptDetail, AttemptView, Generate, QuestionView, QuizView, Result, Save, Start
from app.services.ai_admission import require_free_slot, serialize_generation
from app.services.conversation_service import now, validate_documents
from app.services.document_errors import DocumentError
from app.services.quiz_attempts import detail, expire, finalize, owned_attempt, questions, result, update_answers
from app.services.quiz_performance import performance

router = APIRouter(prefix="/api/v1/quizzes", tags=["Quiz Studio"])
Offset = Annotated[int, Query(ge=0, le=10000)]
Limit = Annotated[int, Query(ge=1, le=50)]


def owned(db, owner, identifier, lock=False):
    query = select(Quiz).where(Quiz.id == identifier, Quiz.user_id == owner)
    item = db.scalar(query.with_for_update() if lock else query)
    if item is None:
        raise TutorError("quiz_not_found", "Quiz not found.", 404)
    return item


def view(quiz):
    value = QuizView.model_validate(quiz)
    if quiz.status == "generating" and quiz.expires_at <= now():
        return value.model_copy(update={"status": "failed", "error_message": "Generation expired. Start a new request."})
    return value


def require_ready(quiz):
    if quiz.status != "ready":
        raise TutorError("quiz_unavailable", "This quiz is not ready.", 409)


def weak_scope(db, owner, data, settings):
    weak = performance(db, owner, settings)["weak_topics"][:3]
    if not weak:
        raise TutorError("no_weak_topics", "Complete more graded questions before generating targeted practice.", 422)
    rows = db.execute(select(QuizQuestion.prompt, QuizQuestion.sources, QuizQuestion.topic_key)
        .join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
        .join(QuizAttempt, QuizAttempt.id == QuizAnswer.attempt_id)
        .where(QuizAttempt.user_id == owner, QuizAttempt.status == "graded",
               QuizQuestion.topic_key.in_([item["key"] for item in weak]))
        .order_by(QuizAttempt.submitted_at.desc(), QuizAnswer.id).limit(120)).all()
    ids = {UUID(source["document_id"]) for row in rows for source in row.sources}
    # Only prior weak topics with surviving, owned, indexed sources can be practiced.
    from app.ai.vector_store import collection_name
    docs = list(db.scalars(select(Document.id).where(
        Document.id.in_(ids), Document.user_id == owner, Document.status == DocumentStatus.READY,
        Document.vector_collection == collection_name(settings),
    ).order_by(Document.id).limit(settings.quiz_max_documents)))
    if not docs:
        raise TutorError("no_weak_sources", "No ready PDFs remain for those weak topics.", 422)
    labels = [item["label"] for item in weak if any(row.topic_key == item["key"] and
              any(UUID(source["document_id"]) in docs for source in row.sources) for row in rows)]
    avoid = list(dict.fromkeys(row.prompt for row in rows))[:12]
    return data.model_copy(update={"document_ids": docs, "focus": ", ".join(labels)[:160]}), avoid


@router.get("/config")
def config(owner: Owner):
    settings = get_settings()
    return {"max_documents": settings.quiz_max_documents, "max_questions": settings.quiz_max_questions}


@router.get("/performance/summary")
def summary(owner: Owner, db: DB):
    return performance(db, owner.id, get_settings())


@router.post("/generate", status_code=201, response_model=QuizView)
def generate(data: Generate, owner: Owner, db: DB):
    from app.api.subjects import owned_subject
    owner_id, settings = owner.id, get_settings()
    fingerprint = sha256(data.model_dump_json(exclude={"request_id", *(["subject_id"] if data.subject_id is None else [])}).encode()).hexdigest()
    serialize_generation(db)
    previous = db.scalar(select(QuizUsage).where(QuizUsage.user_id == owner_id, QuizUsage.request_id == data.request_id))
    if previous:
        if previous.fingerprint != fingerprint:
            raise TutorError("request_conflict", "That generation ID was used for another request.", 409)
        if previous.quiz_id is None:
            raise TutorError("quiz_deleted", "That quiz was deleted. Start a new request.", 410)
        return view(owned(db, owner_id, previous.quiz_id))
    if data.question_count > settings.quiz_max_questions:
        raise TutorError("quiz_limit", f"Choose at most {settings.quiz_max_questions} questions.", 422)
    current = now()
    require_free_slot(db, current)
    daily_quota = db.scalar(select(func.count()).select_from(QuizUsage).where(
        QuizUsage.user_id == owner_id, QuizUsage.created_at > current - timedelta(days=1),
    ))
    if daily_quota >= settings.quiz_daily_generations:
        raise TutorError("quiz_quota", "You reached your rolling daily quiz generation limit.", 429)
    avoid = []
    if data.weak_practice:
        data, avoid = weak_scope(db, owner_id, data, settings)
    if not data.document_ids:
        raise TutorError("document_required", "Select at least one ready PDF.", 422)
    doc_ids = validate_documents(db, owner_id, data.document_ids, settings, lock=True, max_documents=settings.quiz_max_documents)
    subject = owned_subject(db, owner_id, data.subject_id) if data.subject_id else None
    filenames = dict(db.execute(select(Document.id, Document.filename).where(Document.id.in_(doc_ids))).all())
    title = (data.focus or filenames[doc_ids[0]].removesuffix(".pdf") or "Study")[:105] + " quiz"
    quiz = Quiz(user_id=owner_id, title=title, kind=data.kind, difficulty=data.difficulty, question_count=data.question_count,
                focus=data.focus, minutes=data.minutes, subject_label=subject.name if subject else None, subject_key=subject.normalized if subject else None, sources=[dict(document_id=str(key), filename=filenames[key]) for key in doc_ids],
                status="generating", expires_at=current + timedelta(minutes=3), model=settings.gemini_chat_model)
    db.add(quiz)
    db.flush()
    quiz_id = quiz.id
    usage = QuizUsage(user_id=owner_id, quiz_id=quiz_id, request_id=data.request_id, fingerprint=fingerprint,
                      status="generating", model=settings.gemini_chat_model)
    db.add(usage)
    db.flush()
    usage_id = usage.id
    db.commit()
    error = None
    try:
        items, token_usage = quiz_generator.generate(db, owner_id, filenames, data, settings, avoid)
    except (TutorError, DocumentError) as failure:
        error = failure
    db.rollback()
    quiz = owned(db, owner_id, quiz_id, lock=True)
    usage = db.get(QuizUsage, usage_id)
    if not error:
        try:
            if quiz.expires_at <= now():
                raise TutorError("generation_timeout", "Generation expired. Start a new request.", 504)
            validate_documents(db, owner_id, doc_ids, settings, lock=True, max_documents=settings.quiz_max_documents)
            if data.weak_practice:
                normalized_prompt = func.btrim(func.regexp_replace(func.lower(QuizQuestion.prompt), "[^[:alnum:]_]+", " ", "g"))
                repeated = db.scalar(select(QuizQuestion.id).join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
                    .join(QuizAttempt, QuizAttempt.id == QuizAnswer.attempt_id)
                    .where(QuizAttempt.user_id == owner_id, QuizAttempt.status == "graded",
                           QuizAnswer.value["answer"].astext.is_not(None),
                           normalized_prompt.in_([quiz_generator.normalized(item["prompt"]) for item in items])).limit(1))
                if repeated is not None:
                    raise quiz_generator.invalid()
        except TutorError as failure:
            error = failure
    if error:
        quiz.status = usage.status = "failed"
        quiz.error_code = getattr(error, "code", "provider_unavailable")
        quiz.error_message = str(error)[:240]
    else:
        db.add_all(QuizQuestion(quiz_id=quiz_id, **item) for item in items)
        quiz.status = usage.status = "ready"
        usage.token_usage = token_usage
    output = view(quiz)
    db.commit()
    return output


@router.get("")
def list_quizzes(owner: Owner, db: DB, offset: Offset = 0, limit: Limit = 15):
    items = db.scalars(select(Quiz).where(Quiz.user_id == owner.id)
        .order_by(Quiz.created_at.desc(), Quiz.id.desc()).offset(offset).limit(limit+1)).all()
    return {"items": [view(item) for item in items[:limit]], "has_more": len(items) > limit}


@router.get("/attempts/{identifier}", response_model=AttemptDetail)
def get_attempt(identifier: UUID, owner: Owner, db: DB):
    attempt = owned_attempt(db, owner.id, identifier)
    quiz = owned(db, owner.id, attempt.quiz_id)
    items = questions(db, quiz.id)
    expire(db, attempt, items)
    response = detail(db, quiz, attempt, items)
    db.commit()
    return response


@router.patch("/attempts/{identifier}/answers", response_model=AttemptDetail)
def save(identifier: UUID, data: Save, owner: Owner, db: DB):
    attempt = owned_attempt(db, owner.id, identifier)
    quiz = owned(db, owner.id, attempt.quiz_id)
    items = questions(db, quiz.id)
    expire(db, attempt, items)
    if attempt.status != "in_progress":
        db.commit()
        raise TutorError("attempt_closed", "This attempt is closed. Open the results.", 409)
    update_answers(db, attempt, items, data.answers)
    db.flush()
    response = detail(db, quiz, attempt, items)
    db.commit()
    return response


@router.post("/attempts/{identifier}/submit", response_model=Result)
@router.get("/attempts/{identifier}/results", response_model=Result)
def review(identifier: UUID, owner: Owner, db: DB, request: Request):
    attempt = owned_attempt(db, owner.id, identifier)
    quiz = owned(db, owner.id, attempt.quiz_id)
    items = questions(db, quiz.id)
    expire(db, attempt, items)
    if request.method == "POST":
        finalize(db, attempt, items, now())
    output = result(db, quiz, attempt, items)
    db.commit()
    return output


@router.get("/{quiz_id}", response_model=QuizView)
def get_quiz(quiz_id: UUID, owner: Owner, db: DB):
    return view(owned(db, owner.id, quiz_id))


@router.get("/{quiz_id}/questions", response_model=list[QuestionView])
def get_questions(quiz_id: UUID, owner: Owner, db: DB):
    require_ready(owned(db, owner.id, quiz_id))
    return [QuestionView.model_validate(q) for q in questions(db, quiz_id)]


@router.delete("/{quiz_id}", status_code=204)
def delete_quiz(quiz_id: UUID, owner: Owner, db: DB):
    quiz = owned(db, owner.id, quiz_id, lock=True)
    if quiz.status == "generating" and quiz.expires_at > now():
        raise TutorError("quiz_busy", "Wait for generation before deleting this quiz.", 409)
    db.delete(quiz)
    db.commit()
    return Response(status_code=204)


@router.post("/{quiz_id}/attempts", status_code=201, response_model=AttemptDetail)
@router.post("/{quiz_id}/retake", status_code=201, response_model=AttemptDetail)
def start(quiz_id: UUID, data: Start, owner: Owner, db: DB):
    quiz = owned(db, owner.id, quiz_id, lock=True)
    require_ready(quiz)
    items = questions(db, quiz_id)
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id,
                        QuizAttempt.user_id == owner.id, QuizAttempt.request_id == data.request_id).with_for_update())
    if attempt is None:
        started = now()
        attempt = QuizAttempt(quiz_id=quiz_id, request_id=data.request_id, user_id=owner.id,
                              status="in_progress", started_at=started, total_marks=sum(q.max_marks for q in items),
                              earned_marks=0, deadline=started + timedelta(minutes=quiz.minutes) if quiz.minutes else None)
        db.add(attempt)
        db.flush()
    expire(db, attempt, items)
    output = detail(db, quiz, attempt, items)
    db.commit()
    return output


@router.get("/{quiz_id}/attempts")
def list_attempts(quiz_id: UUID, owner: Owner, db: DB, offset: Offset = 0, limit: Limit = 12):
    owned(db, owner.id, quiz_id)
    rows = db.scalars(select(QuizAttempt).where(QuizAttempt.quiz_id == quiz_id, QuizAttempt.user_id == owner.id)
        .order_by(QuizAttempt.started_at.desc(), QuizAttempt.id.desc()).offset(offset).limit(limit+1)).all()
    return {"items": [AttemptView.model_validate(item) for item in rows[:limit]], "has_more": len(rows) > limit}
