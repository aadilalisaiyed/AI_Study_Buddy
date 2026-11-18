from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import delete, select

from app.ai.llm import TutorError
from app.models.document import Document
from app.models.planner import CalendarEventLink, RevisionDocument, RevisionProposal, RevisionSession
from app.models.quiz import Quiz
from app.schemas.planner import PlanInput, ProposalInput, ProposalView
from app.services.conversation_service import now
from app.services.google_calendar import GoogleError, access, connection, lock_owner, provider, rate
from app.services.revision_engine import event_link, overlaps, plan_instants, require_local_slot, session, session_view

SYNC_ERROR = "Google synchronization failed. Retry the same approved operation."


def owned_proposal(db, owner, identifier):
    item = db.scalar(select(RevisionProposal).where(RevisionProposal.id == identifier, RevisionProposal.user_id == owner))
    if not item:
        raise TutorError("proposal_not_found", "Revision proposal not found.", 404)
    return item


def public(db, proposal):
    item = session(db, proposal.user_id, proposal.session_id) if proposal.session_id else None
    hidden = {"document_ids", "source_quiz_id"}
    return ProposalView(
        id=proposal.id, action=proposal.action, status=proposal.status, session_id=proposal.session_id,
        details={key: value for key, value in proposal.payload.items() if key not in hidden},
        calendar_name=proposal.destination["name"] if proposal.destination else None,
        expires_at=proposal.expires_at, error=proposal.error,
        session=session_view(db, item, event_link(db, item.id)) if item else None,
    )


def check_sources(db, owner, plan):
    if plan.source_quiz_id and not db.scalar(select(Quiz.id).where(Quiz.id == plan.source_quiz_id, Quiz.user_id == owner).with_for_update(key_share=True, read=True)):
        raise TutorError("source_not_found", "Source quiz not found.", 404)
    ids = set(plan.document_ids)
    if ids != set(db.scalars(select(Document.id).where(Document.id.in_(ids), Document.user_id == owner).with_for_update(key_share=True, read=True))):
        raise TutorError("source_not_found", "Source document not found.", 404)


def remote_destination(db, owner, item):
    row = connection(db, owner)
    if not row or row.status != "connected":
        raise TutorError("calendar_reconnect", "Connect Google Calendar before choosing synchronization.", 409)
    link = event_link(db, item.id) if item else None
    if link:
        if link.account_id != row.google_account_id:
            raise TutorError("calendar_account", "Reconnect the Google account originally used for this session.", 409)
        if link.status != "deleted":
            selected = row.selected_calendar
            if not selected or selected["id"] != link.calendar_id:
                # The approval must show the original destination and timezone.
                raise TutorError("calendar_selection", "Select the original Google Calendar for this session.", 409)
    if not row.selected_calendar:
        raise TutorError("calendar_selection", "Select a writable Google Calendar first.", 409)
    return {**row.selected_calendar, "connection_id": str(row.id), "account_id": row.google_account_id}


def propose(db, owner, data: ProposalInput):
    lock_owner(db, owner)
    marker = sha256(data.model_dump_json(exclude={"request_id"}).encode()).hexdigest()
    old = db.scalar(select(RevisionProposal).where(RevisionProposal.user_id == owner,
                                                   RevisionProposal.request_id == data.request_id))
    if old:
        if old.fingerprint != marker:
            raise TutorError("proposal_conflict", "That request ID belongs to a different proposal.", 409)
        return public(db, old)
    item = session(db, owner, data.session_id) if data.session_id else None
    if item and item.status != "scheduled":
        raise TutorError("session_closed", "Only scheduled sessions can be changed.", 409)
    link = event_link(db, item.id) if item else None
    if data.google and data.action == "cancel" and (not link or link.status == "deleted"):
        raise TutorError("calendar_link", "There is no Google event linked to that session.", 409)
    if data.plan:
        check_sources(db, owner, data.plan)
        start, end = plan_instants(data.plan)
        require_local_slot(db, owner, start, end, data.session_id)
        payload = data.plan.model_dump(mode="json", exclude={"local_date", "local_time", "fold", "duration"})
        payload.update(start_at=start.isoformat(), end_at=end.isoformat())
    else:
        payload = {key: getattr(item, key) for key in ("title", "subject", "topic", "description", "timezone", "reminder_minutes")}
        payload.update(start_at=item.start_at.isoformat(), end_at=item.end_at.isoformat())
    if item:
        payload["previous_start_at"] = item.start_at.isoformat()
        payload["previous_end_at"] = item.end_at.isoformat()
    if not data.google and link and link.status != "deleted":
        payload["leaves_remote_unchanged"] = True
    proposal = RevisionProposal(
        user_id=owner, request_id=data.request_id, fingerprint=marker, session_id=data.session_id,
        action=data.action, before_version=item.version if item else None, status="pending",
        payload=payload, destination=remote_destination(db, owner, item) if data.google else None,
        expires_at=now() + timedelta(minutes=10),
    )
    db.add(proposal)
    db.flush()
    view = public(db, proposal)
    db.commit()
    return view


def approve(db, owner, identifier):
    lock_owner(db, owner)
    proposal = owned_proposal(db, owner, identifier)
    if proposal.status == "pending":
        if now() >= proposal.expires_at:
            raise TutorError("proposal_expired", "This review expired. Create a new proposal.", 409)
        if proposal.session_id and session(db, owner, proposal.session_id).version != proposal.before_version:
            raise TutorError("proposal_stale", "The session changed. Review a fresh proposal.", 409)
        proposal.status = "approved"
        proposal.approved_at = now()
    action = proposal.action
    db.commit()
    return action


def check_approved(proposal):
    if proposal.status == "pending" or proposal.approved_at is None:
        raise TutorError("confirmation_required", "The exact proposal must be approved in the Planner first.", 403)
    if proposal.status != "done" and now() > proposal.approved_at + timedelta(hours=24):
        raise TutorError("approval_expired", "This approval expired. Create a new proposal.", 409)


def apply_local(db, proposal):
    payload = proposal.payload
    owner = proposal.user_id
    action = proposal.action
    item = session(db, owner, proposal.session_id) if proposal.session_id else None
    if item and (item.version != proposal.before_version or item.status != "scheduled"):
        raise TutorError("proposal_stale", "The session changed. Review a fresh proposal.", 409)
    if action in ("update", "create"):
        fields = {key: payload[key] for key in ("title", "description", "subject", "topic", "timezone", "reminder_minutes")}
        start, end = (datetime.fromisoformat(payload[key]) for key in ("start_at", "end_at"))
        if start <= now():
            raise TutorError("invalid_schedule", "This session time has passed. Choose a future time.", 422)
        require_local_slot(db, owner, start, end, item.id if item else None)
        quiz_id = UUID(payload["source_quiz_id"]) if payload.get("source_quiz_id") else None
        documents = list(dict.fromkeys(UUID(value) for value in payload["document_ids"]))
        if quiz_id and not db.scalar(select(Quiz.id).where(Quiz.id == quiz_id, Quiz.user_id == owner).with_for_update(key_share=True, read=True)):
            raise TutorError("source_not_found", "The source quiz is no longer available.", 404)
        surviving = set(db.scalars(select(Document.id).where(Document.id.in_(documents), Document.user_id == owner)
                                   .with_for_update(key_share=True, read=True)))
        if surviving != set(documents):
            raise TutorError("source_not_found", "A source document is no longer available.", 404)
        fields.update(start_at=start, end_at=end, source_quiz_id=quiz_id)
        if action == "create":
            item = RevisionSession(id=uuid4(), user_id=owner, status="scheduled", version=0, **fields)
            db.add(item)
            db.flush()
            proposal.session_id = item.id
        else:
            for key, value in fields.items():
                setattr(item, key, value)
            db.execute(delete(RevisionDocument).where(RevisionDocument.session_id == item.id))
        db.add_all(RevisionDocument(session_id=item.id, document_id=value) for value in documents)
    elif action == "cancel":
        item.status = "cancelled"
    elif item.start_at <= now():
        raise TutorError("invalid_schedule", "This session time has passed. Reschedule it first.", 422)
    item.version += 1
    proposal.applied_version = item.version
    link = event_link(db, item.id)
    if proposal.destination:
        target = proposal.destination
        if not link:
            link = CalendarEventLink(session_id=item.id, connection_id=UUID(target["connection_id"]),
                account_id=target["account_id"], calendar_id=target["id"], event_id="asb" + item.id.hex, status="pending")
            db.add(link)
        elif link.account_id != target["account_id"] or link.calendar_id != target["id"]:
            raise TutorError("calendar_selection", "The linked calendar does not match this approval.", 409)
        link.status = "pending"
        link.last_error = None
    elif link and link.status != "deleted":
        link.status = "out_of_sync"
    if not proposal.destination:
        proposal.status = "done"
    db.flush()


def google_payload(proposal):
    data = proposal.payload
    reminder = data["reminder_minutes"]
    return dict(
        summary=data["title"], description=data["description"],
        start=dict(dateTime=data["start_at"], timeZone=data["timezone"]),
        end=dict(dateTime=data["end_at"], timeZone=data["timezone"]),
        reminders={"useDefault": False, "overrides": [] if reminder is None else [{"method": "popup", "minutes": reminder}]},
        extendedProperties={"private": {"asb_session": str(proposal.session_id), "asb_operation": str(proposal.id)}},
    )


def write_google(db, proposal, item, link):
    target = proposal.destination
    row = connection(db, proposal.user_id)
    if not row or str(row.id) != target["connection_id"] or row.google_account_id != target["account_id"]:
        raise TutorError("calendar_reconnect", "Reconnect the Google account used for this approval.", 409)
    rate(db, proposal.user_id)
    token = access(db, row)
    adapter = provider()
    calendar, identifier = link.calendar_id, link.event_id
    existing = adapter.event(token, calendar, identifier)
    if existing:
        private = existing.get("extendedProperties", {}).get("private", {})
        if private.get("asb_session") != str(item.id):
            raise TutorError("calendar_conflict", "The Google event does not match the app-managed session.", 409)
        if proposal.action != "cancel" and private.get("asb_operation") == str(proposal.id):
            # Same immutable approval after a lost response. Google may also be
            # edited directly after that write; full payload comparison protects the retry.
            body = google_payload(proposal)
            try:
                same = (existing.get("summary") == body["summary"]
                        and (existing.get("description") or "") == body["description"]
                        and all(datetime.fromisoformat(existing[key]["dateTime"]) ==
                                datetime.fromisoformat(body[key]["dateTime"]) for key in ("start", "end"))
                        and existing.get("reminders", {}).get("useDefault") is False
                        and existing.get("reminders", {}).get("overrides", []) == body["reminders"]["overrides"])
            except (ValueError, KeyError, TypeError):
                same = False
            if same and existing.get("etag"):
                return "synced", existing["etag"]
            raise TutorError("calendar_conflict", "The Google event changed after synchronization. Review it in Google Calendar.", 409)
        if not link.etag or existing.get("etag") != link.etag:
            raise TutorError("calendar_conflict", "The event changed in Google Calendar. Review it there before taking further action.", 409)
    elif link.etag and proposal.action != "cancel":
        raise TutorError("calendar_conflict", "The linked event was removed in Google Calendar.", 409)
    if proposal.action == "cancel":
        if existing:
            adapter.remove(token, calendar, identifier, link.etag)
        return "deleted", None
    if item.start_at <= now():
        raise TutorError("invalid_schedule", "This session time has passed. Reschedule it first.", 422)
    known = adapter.busy(token, target, item.start_at, item.end_at, excluding=identifier)
    if overlaps(known, item.start_at, item.end_at):
        raise TutorError("calendar_conflict", "The approved time conflicts with the selected Google Calendar.", 409)
    body = google_payload(proposal)
    result = (adapter.update(token, calendar, identifier, link.etag, body) if existing else
              adapter.create(token, calendar, {"id": identifier, **body}))
    if result.get("id") != identifier or not result.get("etag"):
        raise GoogleError(503, "Google did not confirm the event. Retry the same approved operation.")
    return "synced", result["etag"]


def execute(db, owner, identifier, action=None):
    lock_owner(db, owner)
    proposal = owned_proposal(db, owner, identifier)
    if action is not None and proposal.action != action:
        raise TutorError("confirmation_required", "This approval belongs to a different operation.", 403)
    check_approved(proposal)
    if proposal.status == "done":
        return public(db, proposal)
    if proposal.applied_version is None:
        apply_local(db, proposal)
        response = public(db, proposal)
        db.commit()
        if response.status == "done":
            return response
        lock_owner(db, owner)
        proposal = owned_proposal(db, owner, identifier)
        if proposal.status == "done":
            return public(db, proposal)
    item = session(db, owner, proposal.session_id)
    if item.version != proposal.applied_version:
        raise TutorError("proposal_stale", "The session changed. Review a fresh proposal.", 409)
    link = event_link(db, item.id)
    try:
        status, tag = write_google(db, proposal, item, link)
    except TutorError as error:
        proposal.status = "failed"
        proposal.error = str(error)[:240]
        link.status = "reconnect_required" if error.code == "calendar_reconnect" else "sync_failed"
        link.last_error = proposal.error
        row = connection(db, owner)
        if row and error.code == "calendar_reconnect":
            row.status = "reconnect_required"
    else:
        proposal.status = "done"
        proposal.error = link.last_error = None
        link.status, link.etag, link.last_synced_at = status, tag, now()
        connection(db, owner).last_synced_at = link.last_synced_at
    response = public(db, proposal)
    db.commit()
    return response


def completed(db, owner, identifier):
    lock_owner(db, owner)
    item = session(db, owner, identifier)
    if item.status == "cancelled":
        raise TutorError("session_closed", "A cancelled session cannot be marked completed.", 409)
    if item.status != "completed":
        item.status, item.completed_at, item.version = "completed", now(), item.version + 1
    view = session_view(db, item, event_link(db, item.id))
    db.commit()
    return view
