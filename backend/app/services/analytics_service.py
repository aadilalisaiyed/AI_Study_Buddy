from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from sqlalchemy import Date, cast, func, select

from app.core.config import get_settings
from app.models.conversation import Conversation, Message
from app.models.document import Document, DocumentStatus
from app.models.planner import RevisionPreferences, RevisionSession
from app.models.quiz import Quiz, QuizAnswer, QuizAttempt, QuizQuestion
from app.services.quiz_grader import percentage


def period(db, owner, days, start, end, zone):
    preferences = db.get(RevisionPreferences, owner)
    try:
        tz = ZoneInfo(zone or (preferences.settings.get("timezone") if preferences else None) or "Asia/Kolkata")
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Unknown timezone") from exc
    today = datetime.now(tz).date()
    if (start is None) != (end is None):
        raise HTTPException(422, "Supply both custom dates")
    if start is None:
        start, end = today - timedelta(days=days-1), today
    if start > end or (end-start).days > 365 or end >= date.max:
        raise HTTPException(422, "Select an ordered range of at most 366 days")
    return tz, today, start, end


def ratio(earned, available):
    return percentage(earned, available) if available else None


def streaks(days, today):
    current, longest, previous = 0, 0, None
    for day in sorted(set(days)):
        current = current + 1 if previous and day-previous == timedelta(days=1) else 1
        longest = max(current, longest)
        previous = day
    return current if previous and 0 <= (today-previous).days <= 1 else 0, longest


def report(db, owner, interval, offset, limit):
    tz, today, first, last = interval
    now = datetime.now(timezone.utc)
    lower = datetime.combine(first, time.min, tz)
    upper = datetime.combine(last+timedelta(days=1), time.min, tz)

    def within(column):
        return (column >= lower, column < upper)

    def day(column):
        return cast(func.timezone(tz.key, column), Date)

    def counts(query, column):
        grouped = day(column)
        return dict(db.execute(query.with_only_columns(grouped, func.count()).group_by(grouped)).all())

    A, Q, V, R = QuizAttempt, QuizQuestion, QuizAnswer, RevisionSession
    attempts = select(A.id, A.quiz_id, A.started_at, A.submitted_at, A.earned_marks, A.total_marks, Quiz.subject_key, Quiz.subject_label).join(
        Quiz, Quiz.id == A.quiz_id
    ).where(A.user_id == owner, Quiz.user_id == owner, A.status == "graded",
            *within(A.submitted_at)).cte("owned_attempts")
    a = attempts.c
    score = a.earned_marks * Decimal(100) / func.nullif(a.total_marks, 0)
    elapsed = func.greatest(0, func.extract("epoch", a.submitted_at-a.started_at))
    num, unique, average, seconds = db.execute(select(
        func.count(a.id), func.count(func.distinct(a.quiz_id)), func.avg(score), func.sum(elapsed)
    )).one()

    subjects = [dict(label=label or "Uncategorized", quizzes=quizzes_n, average_score=round(float(avg), 1) if avg is not None else None)
                for _, label, quizzes_n, avg in db.execute(select(
                    a.subject_key, func.min(a.subject_label), func.count(func.distinct(a.quiz_id)), func.avg(score)
                ).group_by(a.subject_key).order_by(a.subject_key).limit(100))]
    answer = V.value["answer"].astext
    objective = Q.kind.in_(("mcq", "boolean"))
    full = V.earned_marks == V.max_marks
    base = select().select_from(attempts).join(V, V.attempt_id == a.id).join(
        Q, (Q.id == V.question_id) & (Q.quiz_id == a.quiz_id)
    ).where(V.graded_at.is_not(None), answer.is_not(None), func.btrim(answer) != "")
    answered, correct, objective_n, objective_correct, marks, maximum = db.execute(base.with_only_columns(
        func.count(), func.count().filter(full), func.count().filter(objective),
        func.count().filter(objective, full), func.sum(V.earned_marks), func.sum(V.max_marks)
    )).one()
    breakdown = (func.count(), func.count().filter(full), func.sum(V.earned_marks), func.sum(V.max_marks))

    def item(label, n, exact, earned, total):
        return dict(label=label, questions=n, correct=exact, earned=earned, available=total,
                    percentage=ratio(earned, total))

    dims = {name: [item(*row) for row in db.execute(base.with_only_columns(
        col, *breakdown
    ).group_by(col).order_by(col))] for col, name in ((Q.kind, "types"), (Q.difficulty, "difficulties"))}
    # Quiz Studio persists a normalized topic key and uses it for weakness scoring.
    topic_groups = base.with_only_columns(
        Q.topic_key.label("key"), func.min(Q.topic).label("label"), *breakdown,
        func.max(a.submitted_at).label("last_practiced"), func.array_agg(func.distinct(Q.topic)).label("originals"),
    ).group_by(Q.topic_key)
    topic_order = (func.sum(V.earned_marks)*Decimal(1)/func.nullif(func.sum(V.max_marks), 0), Q.topic_key)

    def topics(query):
        return [dict(item(label, n, exact, earned, total), key=key, last_practiced=latest, originals=originals)
                for key, label, n, exact, earned, total, latest, originals in db.execute(query)]

    settings = get_settings()
    weak = topics(topic_groups.having(func.count() >= settings.quiz_weak_min_answers)
                  .order_by(*topic_order).limit(80))
    pending_topics = db.scalars(select(func.lower(func.btrim(R.topic))).where(
        R.user_id == owner, R.status == "scheduled", R.start_at >= now
    ).distinct()).all()
    weak = [dict(row, priority="Scheduled" if row["label"].lower().strip() in pending_topics else "Review")
            for row in weak if row["percentage"] is not None and row["percentage"] < settings.quiz_weak_threshold][:10]

    midpoint = datetime.combine(first + timedelta(days=((last-first).days+1)//2), time.min, tz)
    earlier, later = a.submitted_at < midpoint, a.submitted_at >= midpoint
    previous_earned = func.sum(V.earned_marks).filter(earlier)
    previous_max = func.sum(V.max_marks).filter(earlier)
    recent_earned = func.sum(V.earned_marks).filter(later)
    recent_max = func.sum(V.max_marks).filter(later)
    previous_ratio = previous_earned * Decimal(100) / func.nullif(previous_max, 0)
    recent_ratio = recent_earned * Decimal(100) / func.nullif(recent_max, 0)
    improvement = db.execute(base.with_only_columns(
        func.min(Q.topic), previous_earned, previous_max, recent_earned, recent_max
    ).group_by(Q.topic_key).having(
        func.count().filter(earlier) >= settings.quiz_weak_min_answers,
        func.count().filter(later) >= settings.quiz_weak_min_answers,
        func.round(previous_ratio, 2) < settings.quiz_weak_threshold,
        func.round(recent_ratio, 2) > func.round(previous_ratio, 2),
    ).order_by((recent_ratio-previous_ratio).desc(), Q.topic_key).limit(1)).first()
    topic_change = None
    if improvement:
        label, earned_before, max_before, earned_after, max_after = improvement
        topic_change = dict(label=label, earlier=ratio(earned_before, max_before),
                            later=ratio(earned_after, max_after), later_start=midpoint.date())

    recent = select(a.id, a.submitted_at, a.earned_marks, a.total_marks).order_by(
        a.submitted_at.desc(), a.id.desc()
    ).limit(120).subquery()
    b = recent.c
    correctness = base.with_only_columns(a.id.label("id"), func.count().filter(objective).label("n"),
                                        func.count().filter(objective, full).label("correct")).where(
        a.id.in_(select(b.id))
    ).group_by(a.id).subquery()
    trend = [dict(id=identifier, date=stamp, day=stamp.astimezone(tz).date(), score=ratio(earned, total),
                  accuracy=ratio(yes, n or 0))
             for identifier, stamp, earned, total, n, yes in db.execute(
                 select(b.id, b.submitted_at, b.earned_marks, b.total_marks, correctness.c.n, correctness.c.correct)
                 .outerjoin(correctness, correctness.c.id == b.id).order_by(b.submitted_at, b.id))]
    quizzes = counts(select().select_from(attempts), a.submitted_at)
    tutor_base = select().select_from(Message).join(Conversation).where(
        Conversation.user_id == owner, Message.role == "user"
    )
    tutor = counts(tutor_base.where(*within(Message.created_at)), Message.created_at)
    completed = counts(select().select_from(R).where(
        R.user_id == owner, R.status == "completed", *within(R.completed_at)
    ), R.completed_at)
    activity = [
        dict(date=d, quizzes=quizzes.get(d, 0), tutor=tutor.get(d, 0), revisions=completed.get(d, 0))
        for d in (first+timedelta(days=i) for i in range((last-first).days+1))
    ]
    active = [row["date"] for row in activity if row["quizzes"]+row["tutor"]+row["revisions"]]
    current, longest = streaks(active, today)

    revision = select().select_from(R).where(R.user_id == owner, *within(R.start_at))
    duration = func.extract("epoch", R.end_at-R.start_at)
    done = R.status == "completed"
    cancelled = R.status == "cancelled"
    missed = (R.status == "scheduled") & (R.end_at <= now)
    scheduled, complete_n, cancelled_n, pending_n, planned, completed_plan = db.execute(revision.with_only_columns(
        func.count().filter(~cancelled), func.count().filter(done), func.count().filter(cancelled),
        func.count().filter(missed), func.sum(duration).filter(~cancelled), func.sum(duration).filter(done)
    )).one()
    week = cast(func.date_trunc("week", func.timezone(tz.key, R.start_at)), Date)
    weekly = [dict(week=key, planned=n, completed=m) for key,n,m in db.execute(revision.with_only_columns(
        week, func.count().filter(~cancelled), func.count().filter(done)
    ).group_by(week).order_by(week))]
    subject = func.coalesce(func.nullif(func.btrim(R.subject), ""), "Uncategorized")
    revision_subjects = [dict(label=key, sessions=n) for key,n in db.execute(revision.with_only_columns(
        subject, func.count()
    ).where(~cancelled).group_by(subject).order_by(func.count().desc(), subject).limit(30))]
    upcoming = [dict(id=identifier, title=title, start_at=stamp) for identifier,title,stamp in db.execute(
        select(R.id, R.title, R.start_at).where(R.user_id == owner, R.status == "scheduled", R.start_at > now)
        .order_by(R.start_at, R.id).limit(5))]
    conversations = db.scalar(select(func.count()).select_from(Conversation).where(
        Conversation.user_id == owner, *within(Conversation.created_at)
    ))
    docs = db.execute(select(
        func.count().filter(*within(Document.created_at), Document.status.not_in((DocumentStatus.PENDING, DocumentStatus.UPLOADING))),
        func.count().filter(Document.status == DocumentStatus.READY),
        func.count().filter(Document.status == DocumentStatus.FAILED, *within(Document.created_at)),
        func.count().filter(*within(Document.processed_at)),
    ).where(Document.user_id == owner, Document.status != DocumentStatus.DELETING)).one()
    score_change = None
    if len(trend) >= 6 and all(row["score"] is not None for row in trend[-6:]):
        score_change = round((sum(row["score"] for row in trend[-3:])-sum(row["score"] for row in trend[-6:-3]))/3, 1)
    return dict(
        range=dict(start=first, end=last, timezone=tz.key), overview=dict(attempts=num, quizzes=unique,
            questions=answered, correct=correct, objective_questions=objective_n, objective_correct=objective_correct,
            accuracy=ratio(objective_correct, objective_n), mark_score=ratio(marks, maximum),
            average_score=round(float(average), 1) if average is not None else None, quiz_seconds=int(seconds or 0)),
        trend=trend, topics=topics(topic_groups.order_by(*topic_order).offset(offset).limit(limit)),
        weak_topics=weak, **dims,
        subjects=subjects,
        activity=activity, consistency=dict(active_days=len(active), current=current, longest=longest),
        revision=dict(scheduled=scheduled, completed=complete_n, cancelled=cancelled_n, overdue=pending_n,
                      rate=ratio(complete_n, complete_n+pending_n), planned_minutes=int((planned or 0)/60),
                      completed_planned_minutes=int((completed_plan or 0)/60), weekly=weekly,
                      subjects=revision_subjects, upcoming=upcoming),
        tutor=dict(conversations=conversations, questions=sum(tutor.values()), active_days=len(tutor)),
        library=dict(zip(("uploaded", "ready", "failed", "processed"), docs)),
        insights=dict(score_change=score_change, topic_change=topic_change),
    )
