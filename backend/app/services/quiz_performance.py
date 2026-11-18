from decimal import Decimal

from sqlalchemy import func, select

from app.models.quiz import QuizAnswer, QuizAttempt, QuizQuestion
from app.services.quiz_grader import percentage


def performance(db, owner, settings):
    attempts = QuizAttempt
    completed = (attempts.user_id == owner, attempts.status == "graded")
    count, distinct, avg = db.execute(select(
        func.count(), func.count(func.distinct(attempts.quiz_id)),
        func.avg(attempts.earned_marks * Decimal(100) / func.nullif(attempts.total_marks, 0)),
    ).where(*completed)).one()
    base = select().select_from(QuizAnswer).join(attempts, QuizAnswer.attempt_id == attempts.id).join(
        QuizQuestion, QuizAnswer.question_id == QuizQuestion.id,
    ).where(*completed)
    answered = QuizAnswer.value["answer"].astext.is_not(None)
    full = QuizAnswer.earned_marks == QuizAnswer.max_marks
    total_answered, correct, partial, total_questions = db.execute(base.with_only_columns(
        func.count().filter(answered), func.count().filter(full),
        func.count().filter(QuizAnswer.earned_marks > 0, ~full), func.count(),
    )).one()
    topics = db.execute(base.with_only_columns(
        QuizQuestion.topic_key, func.min(QuizQuestion.topic), func.count(), func.sum(QuizAnswer.earned_marks),
        func.sum(QuizAnswer.max_marks),
    ).where(answered).group_by(QuizQuestion.topic_key).order_by(
        func.sum(QuizAnswer.earned_marks) * 1.0 / func.sum(QuizAnswer.max_marks), QuizQuestion.topic_key,
    ).limit(80)).all()
    breakdown = [dict(key=key, label=label, questions=n, earned=earned, total=total,
                      percentage=percentage(earned, total)) for key, label, n, earned, total in topics]
    weak = [item for item in breakdown if item["questions"] >= settings.quiz_weak_min_answers
            and item["percentage"] < settings.quiz_weak_threshold][:10]
    dimensions = {}
    for column, label in ((QuizQuestion.kind, "types"), (QuizQuestion.difficulty, "difficulties")):
        rows = db.execute(base.with_only_columns(column, func.count(), func.sum(QuizAnswer.earned_marks),
                          func.sum(QuizAnswer.max_marks)).group_by(column).order_by(column)).all()
        dimensions[label] = [dict(label=key, questions=n, earned=earned, total=total,
                                  percentage=percentage(earned, total)) for key, n, earned, total in rows]
    trend = db.scalars(select(attempts).where(*completed).order_by(attempts.submitted_at.desc(), attempts.id.desc()).limit(20)).all()
    return dict(
        attempts_completed=count, quizzes_completed=distinct, questions_answered=total_answered,
        correct=correct, incorrect=total_answered-correct-partial, partial=partial, unanswered=total_questions-total_answered,
        accuracy_percent=percentage(correct, total_answered), average_score_percent=percentage(avg or 0, 100),
        weak_topics=weak, topics=breakdown, **dimensions,
        trend=[dict(id=str(item.id), quiz_id=str(item.quiz_id), date=item.submitted_at, percentage=percentage(item.earned_marks, item.total_marks),
                    duration_seconds=max(0, int((item.submitted_at-item.started_at).total_seconds())))
               for item in reversed(trend)],
    )
