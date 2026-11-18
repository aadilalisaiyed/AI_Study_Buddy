from collections import defaultdict
from uuid import UUID

from sqlalchemy import select

from app.ai.llm import TutorError
from app.models.document import Document, DocumentStatus
from app.models.quiz import QuizAnswer, QuizAttempt, QuizQuestion
from app.schemas.quiz import AttemptDetail, AttemptView, QuestionView, QuizView, Result, Review
from app.services.conversation_service import now
from app.services.quiz_grader import grade, percentage


def questions(db, quiz_id):
    return list(db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == quiz_id).order_by(QuizQuestion.position)))


def owned_attempt(db, owner, identifier):
    attempt = db.scalar(select(QuizAttempt).where(QuizAttempt.id == identifier, QuizAttempt.user_id == owner).with_for_update())
    if attempt is None:
        raise TutorError("attempt_not_found", "Attempt not found.", 404)
    return attempt


def answers(db, attempt):
    return {item.question_id: item for item in db.scalars(select(QuizAnswer).where(QuizAnswer.attempt_id == attempt.id))}


def update_answers(db, attempt, items, provided):
    by_id = {item.id: item for item in items}
    saved = answers(db, attempt)
    for identifier, value in provided.items():
        q = by_id.get(identifier)
        if q is None:
            raise TutorError("invalid_question", "A question does not belong to this attempt.", 422)
        if isinstance(value, str):
            value = value.strip() or None
        valid = value is None or (
            (q.kind == "mcq" and type(value) is int and value in range(4))
            or (q.kind == "boolean" and type(value) is bool)
            or (q.kind == "short" and isinstance(value, str) and len(value) <= 1600)
        )
        if not valid:
            raise TutorError("invalid_answer", "An answer does not match the question format.", 422)
        if identifier not in saved:
            saved[identifier] = QuizAnswer(attempt_id=attempt.id, question_id=identifier, earned_marks=0,
                                           max_marks=q.max_marks, feedback=[])
            db.add(saved[identifier])
        saved[identifier].value = {"answer": value}


def finalize(db, attempt, items, submitted_time):
    if attempt.status == "graded":
        return
    saved = answers(db, attempt)
    total = 0
    for q in items:
        item = saved.get(q.id)
        if item is None:
            item = QuizAnswer(attempt_id=attempt.id, question_id=q.id, value={"answer": None}, max_marks=q.max_marks)
            db.add(item)
        item.earned_marks, item.feedback = grade(q.kind, item.value["answer"], q.key)
        item.graded_at = submitted_time
        total += item.earned_marks
    attempt.earned_marks = total
    attempt.status = "graded"
    attempt.submitted_at = submitted_time
    db.flush()


def expire(db, attempt, items):
    if attempt.status == "in_progress" and attempt.deadline is not None and now() >= attempt.deadline:
        finalize(db, attempt, items, attempt.deadline)


def detail(db, quiz, attempt, items):
    return AttemptDetail(
        **AttemptView.model_validate(attempt).model_dump(), quiz=QuizView.model_validate(quiz),
        questions=[QuestionView.model_validate(q) for q in items],
        answers={key: item.value["answer"] for key, item in answers(db, attempt).items()},
    )


def result(db, quiz, attempt, items):
    if attempt.status != "graded":
        raise TutorError("attempt_open", "Submit the attempt before viewing answers.", 409)
    saved = answers(db, attempt)
    ids = {source["document_id"] for q in items for source in q.sources}
    available = {str(value) for value in db.scalars(select(Document.id).where(
        Document.user_id == attempt.user_id, Document.id.in_([UUID(value) for value in ids]),
        Document.status == DocumentStatus.READY, Document.storage_provider == "supabase",
    ))}
    topics, difficulties = defaultdict(list), defaultdict(list)
    rows = []
    correct = partial = unanswered = 0
    for q in items:
        a = saved[q.id]
        value = a.value["answer"]
        correct += a.earned_marks == q.max_marks
        partial += 0 < a.earned_marks < q.max_marks
        unanswered += value is None
        topics[q.topic_key].append((q.topic, a.earned_marks, q.max_marks))
        difficulties[q.difficulty].append((q.difficulty, a.earned_marks, q.max_marks))
        citations = [{**source, "available": source["document_id"] in available,
                      "chunk_id": source["chunk_id"] if source["document_id"] in available else None} for source in q.sources]
        rows.append(Review(
            **QuestionView.model_validate(q).model_dump(), answer=value, correct_answer=q.key["answer"],
            explanation=q.explanation, topic=q.topic, difficulty=q.difficulty, earned=a.earned_marks,
            feedback=a.feedback, citations=citations,
        ))

    def group(values):
        return [dict(label=group[0][0], questions=len(group), earned=sum(item[1] for item in group),
                     total=sum(item[2] for item in group), percentage=percentage(sum(item[1] for item in group),
                     sum(item[2] for item in group))) for group in values.values()]

    return Result(
        attempt=AttemptView.model_validate(attempt), quiz=QuizView.model_validate(quiz), earned=attempt.earned_marks,
        total=attempt.total_marks, percentage=percentage(attempt.earned_marks, attempt.total_marks),
        correct=correct, partial=partial, unanswered=unanswered, incorrect=len(items)-correct-partial-unanswered,
        duration_seconds=max(0, int((attempt.submitted_at-attempt.started_at).total_seconds())),
        topics=group(topics), difficulties=group(difficulties), questions=rows,
    )
