from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.ai.llm import TutorError
from app.ai.quiz_generator import topic_key
from app.core.config import get_settings
from app.models.document import Document
from app.models.planner import CalendarEventLink, RevisionDocument, RevisionPreferences, RevisionProposal, RevisionSession
from app.models.quiz import Quiz, QuizAnswer, QuizAttempt, QuizQuestion
from app.schemas.planner import Availability, PlanInput, Preferences, Recommendation, SessionView, Slot, zone
from app.services.conversation_service import now
from app.services.google_calendar import access, connection, lock_owner, provider, rate


def preferences(db, owner):
    row = db.get(RevisionPreferences, owner)
    return Preferences.model_validate(row.settings) if row else Preferences(timezone=get_settings().google_calendar_timezone)


def set_preferences(db, owner, values):
    lock_owner(db, owner)
    row = db.get(RevisionPreferences, owner)
    if row is None:
        db.add(RevisionPreferences(user_id=owner, settings=values.model_dump(mode="json")))
    else:
        row.settings = values.model_dump(mode="json")
    db.commit()
    return values


def session(db, owner, identifier):
    item = db.scalar(select(RevisionSession).where(RevisionSession.id == identifier, RevisionSession.user_id == owner))
    if item is None:
        raise TutorError("session_not_found", "Revision session not found.", 404)
    return item


def event_link(db, identifier):
    return db.scalar(select(CalendarEventLink).where(CalendarEventLink.session_id == identifier))


def session_view(db, item, link):
    ids = list(db.scalars(select(RevisionDocument.document_id).where(RevisionDocument.session_id == item.id)))
    retry = db.scalar(select(RevisionProposal.id).where(
        RevisionProposal.session_id == item.id, RevisionProposal.user_id == item.user_id,
        RevisionProposal.applied_version == item.version,
        RevisionProposal.status.in_(["approved", "failed"]),
    ).order_by(RevisionProposal.approved_at.desc()).limit(1)) if link and link.status in {"pending", "sync_failed", "reconnect_required"} else None
    return SessionView(
        **{name: getattr(item, name) for name in (
            "id", "title", "subject", "topic", "description", "start_at", "end_at", "timezone", "reminder_minutes",
            "status", "version", "completed_at", "source_quiz_id",
        )}, document_ids=ids, sync_status=link.status if link else "local_only",
        sync_error=link.last_error if link else None, calendar_id=link.calendar_id if link else None, sync_retry_id=retry,
    )


def list_sessions(db, owner, start=None, end=None, *, offset=0, limit=48):
    query = select(RevisionSession, CalendarEventLink).outerjoin(
        CalendarEventLink, CalendarEventLink.session_id == RevisionSession.id,
    ).where(RevisionSession.user_id == owner)
    if start is not None or end is not None:
        if not start or not end or start.tzinfo is None or end.tzinfo is None or not timedelta(0) < end-start <= timedelta(days=125):
            raise TutorError("invalid_range", "Use a valid timezone-aware range of up to 125 days.", 422)
        query = query.where(RevisionSession.end_at > start, RevisionSession.start_at < end)
    order = RevisionSession.start_at.asc() if start else RevisionSession.start_at.desc()
    entries = db.execute(query.order_by(order, RevisionSession.id).offset(offset).limit(limit + 1)).all()
    return dict(items=[session_view(db, item, link) for item, link in entries[:limit]], has_more=len(entries) > limit)


def resolve_local(day: date, clock: time, timezone_name: str, fold=None):
    wall = datetime.combine(day, clock)
    tz = zone(timezone_name)
    candidates = {}
    for choice in (0, 1):
        instant = wall.replace(tzinfo=tz, fold=choice).astimezone(timezone.utc)
        if instant.astimezone(tz).replace(tzinfo=None) == wall:
            candidates[choice] = instant
    unique = set(candidates.values())
    if not unique:
        raise TutorError("nonexistent_time", "That local time does not exist because the clock changes. Choose another time.", 422)
    if len(unique) > 1 and fold is None:
        raise TutorError("ambiguous_time", "That local time occurs twice. Choose its first or second occurrence.", 422)
    return next(iter(unique)) if len(unique) == 1 else candidates[fold]


def plan_instants(plan: PlanInput):
    start = resolve_local(plan.local_date, plan.local_time, plan.timezone, plan.fold)
    end = start + timedelta(minutes=plan.duration)
    if start <= now() or start > now() + timedelta(days=90):
        raise TutorError("invalid_schedule", "Choose a future start within the next 90 days.", 422)
    return start, end


def intervals(db, owner, start, end, exclude=None):
    query = select(RevisionSession.start_at, RevisionSession.end_at).where(
        RevisionSession.user_id == owner, RevisionSession.status != "cancelled",
        RevisionSession.end_at > start, RevisionSession.start_at < end,
    )
    if exclude:
        query = query.where(RevisionSession.id != exclude)
    return db.execute(query.limit(501)).all()


def overlaps(items, start, end, gap=0):
    buffer = timedelta(minutes=gap)
    return any(begin - buffer < end and finish + buffer > start for begin, finish in items)


def daily_limit(items, start, end, pref):
    tz = zone(pref.timezone)
    current = start.astimezone(tz).date()
    while current <= (end - timedelta(microseconds=1)).astimezone(tz).date():
        left = datetime.combine(current, time.min, tz).astimezone(timezone.utc)
        right = datetime.combine(current + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
        seconds = sum(max(0, (min(finish, right) - max(begin, left)).total_seconds())
                      for begin, finish in [*items, (start, end)])
        if seconds > pref.daily_minutes * 60:
            return False
        current += timedelta(days=1)
    return True


def require_local_slot(db, owner, start, end, exclude=None):
    pref = preferences(db, owner)
    known = intervals(db, owner, start-timedelta(days=2), end+timedelta(days=2), exclude)
    if len(known) > 500 or overlaps(known, start, end, pref.break_minutes):
        raise TutorError("session_conflict", "This time conflicts with a local session or its required break.", 409)
    if not daily_limit(known, start, end, pref):
        raise TutorError("daily_limit", "This session would exceed the daily study limit.", 409)


def available(db, owner, first, last, duration, google):
    pref = preferences(db, owner)
    tz = zone(pref.timezone)
    today = now().astimezone(tz).date()
    if not today <= first <= last <= today + timedelta(days=90) or (last-first).days > 13:
        raise TutorError("invalid_range", "Check up to 14 future days within the next 90 days.", 422)
    start = datetime.combine(first, time.min, tz).astimezone(timezone.utc)
    end = datetime.combine(last + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    local = intervals(db, owner, start-timedelta(days=1), end+timedelta(days=1))
    if len(local) > 500:
        raise TutorError("invalid_range", "Too many local sessions. Try a shorter range.", 422)
    external = []
    calendar_name = None
    if google:
        lock_owner(db, owner)
        row = connection(db, owner)
        if not row or not row.selected_calendar:
            raise TutorError("calendar_selection", "Connect and select a Google Calendar first.", 409)
        calendar_name = row.selected_calendar["name"]
        rate(db, owner)
        try:
            token = access(db, row)
            external = provider().busy(token, row.selected_calendar, start, end)
        except TutorError as error:
            if error.code == "calendar_reconnect":
                row.status = "reconnect_required"
            db.commit()
            raise
        db.commit()
    slots = []
    duration = duration or pref.duration
    for number in range((last-first).days + 1):
        day = first + timedelta(days=number)
        if day.weekday() not in pref.days:
            continue
        cursor = datetime.combine(day, pref.window_start)
        close = datetime.combine(day, pref.window_end)
        for _ in range(96):
            if cursor + timedelta(minutes=duration) > close or len(slots) >= 8:
                break
            try:
                proposed = resolve_local(day, cursor.time(), pref.timezone, 0)
                finish = proposed + timedelta(minutes=duration)
                if (proposed > now() and finish.astimezone(tz).replace(tzinfo=None) <= close
                        and not overlaps(local, proposed, finish, pref.break_minutes)
                        and not overlaps(external, proposed, finish)
                        and daily_limit(local, proposed, finish, pref)):
                    slots.append(Slot(start_at=proposed, end_at=finish, local_date=day,
                                      local_time=cursor.time(), fold=0, timezone=pref.timezone))
                    break
            except TutorError as failure:
                if failure.code != "nonexistent_time":
                    raise
            cursor += timedelta(minutes=15)
    return Availability(scope="google" if google else "local", calendar_name=calendar_name, slots=slots)


def recommendations(db, owner):
    from app.services.quiz_performance import performance
    weak = performance(db, owner, get_settings())["weak_topics"]
    if not weak:
        return []
    keys = [item["key"] for item in weak]
    rows = db.execute(select(QuizQuestion.topic_key, Quiz.id, Quiz.title, Quiz.sources,
                             QuizQuestion.sources, QuizAttempt.submitted_at)
        .join(QuizAnswer, QuizAnswer.question_id == QuizQuestion.id)
        .join(QuizAttempt, QuizAttempt.id == QuizAnswer.attempt_id)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .where(Quiz.user_id == owner, QuizAttempt.user_id == owner, QuizAttempt.status == "graded",
               QuizQuestion.topic_key.in_(keys), QuizAnswer.value["answer"].astext.is_not(None))
        .order_by(QuizAttempt.submitted_at.desc(), QuizAnswer.id).limit(200)).all()
    scheduled = {topic_key(value) for value in db.scalars(select(RevisionSession.topic).where(
        RevisionSession.user_id == owner, RevisionSession.status == "scheduled", RevisionSession.end_at > now(),
    ))}
    pref = preferences(db, owner)
    suggestions = []
    for item in weak:
        key = item["key"]
        prior = next((row for row in rows if row.topic_key == key), None)
        if not prior or key in scheduled:
            continue
        ids = {UUID(source["document_id"]) for source in prior[4]}
        document_ids = list(db.scalars(select(Document.id).where(Document.user_id == owner, Document.id.in_(ids))))
        filename = prior[4][0]["filename"] if prior[4] else ""
        subject = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title() or "General revision"
        days = (now() - prior.submitted_at).days
        score = round(100 - item["percentage"] + min(item["questions"], 12) + min(max(0, days), 14))
        suggestions.append(Recommendation(
            topic=item["label"], subject=subject[:100], priority=score, duration=pref.duration,
            accuracy=item["percentage"], samples=item["questions"], source_quiz_id=prior.id, document_ids=document_ids,
            reason=f"You earned {item['percentage']:g}% of available marks across {item['questions']} answered questions on this topic.",
            activity="Review the source material, recall the main ideas without notes, then try a fresh practice question.",
        ))
    return sorted(suggestions, key=lambda item: (-item.priority, item.topic))[:8]
