from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.ai.llm import TutorError
from app.api.documents import DB, Owner
from app.mcp.client import call
from app.schemas.planner import Availability, Confirm, PlanInput, Preferences, ProposalInput, ProposalView, Recommendation, SessionView
from app.services import calendar_sync, revision_engine

router = APIRouter(prefix="/api/v1/planner", tags=["Revision Planner"])
TOOLS = {"create": "create_revision_session", "update": "reschedule_revision_session",
         "cancel": "cancel_revision_session", "sync": "sync_revision_session"}


@router.get("/preferences", response_model=Preferences)
def preferences(owner: Owner, db: DB):
    return revision_engine.preferences(db, owner.id)


@router.put("/preferences", response_model=Preferences)
def save_preferences(data: Preferences, owner: Owner, db: DB):
    return revision_engine.set_preferences(db, owner.id, data)


@router.get("/recommendations", response_model=list[Recommendation])
def recommendations(owner: Owner):
    return call(owner.id, "get_revision_recommendations")


@router.get("/availability", response_model=Availability)
def availability(first: date, last: date, owner: Owner,
                 duration: Annotated[int | None, Query(ge=15, le=180)] = None, google: bool = False):
    return call(owner.id, "get_calendar_availability", first=first.isoformat(), last=last.isoformat(),
                duration=duration, google=google)


@router.get("/sessions")
def sessions(owner: Owner, start: datetime | None = None, end: datetime | None = None,
             offset: Annotated[int, Query(ge=0, le=20000)] = 0):
    return call(owner.id, "list_revision_sessions", start=start.isoformat() if start else None,
                end=end.isoformat() if end else None, offset=offset)


@router.get("/sessions/{identifier}", response_model=SessionView)
def session(identifier: UUID, owner: Owner, db: DB):
    item = revision_engine.session(db, owner.id, identifier)
    return revision_engine.session_view(db, item, revision_engine.event_link(db, identifier))


@router.post("/sessions/{identifier}/complete", response_model=SessionView)
def complete(identifier: UUID, owner: Owner, db: DB):
    return calendar_sync.completed(db, owner.id, identifier)


@router.post("/proposals", status_code=201, response_model=ProposalView)
def propose(data: ProposalInput, owner: Owner):
    return call(owner.id, "propose_revision_session", data=data.model_dump(mode="json"))


@router.get("/proposals/{identifier}", response_model=ProposalView)
def proposal(identifier: UUID, owner: Owner, db: DB):
    return calendar_sync.public(db, calendar_sync.owned_proposal(db, owner.id, identifier))


@router.post("/proposals/{identifier}/confirm", response_model=ProposalView)
def confirm(identifier: UUID, data: Confirm, owner: Owner, db: DB):
    owner_id = owner.id
    action = calendar_sync.approve(db, owner_id, identifier)
    return call(owner_id, TOOLS[action], proposal_id=str(identifier))


@router.post("/sessions/{identifier}/sync", response_model=ProposalView)
def retry_sync(identifier: UUID, proposal_id: UUID, data: Confirm, owner: Owner, db: DB):
    owner_id = owner.id
    item = calendar_sync.owned_proposal(db, owner_id, proposal_id)
    if item.session_id != identifier or not item.destination:
        raise TutorError("proposal_not_found", "Calendar approval not found for this session.", 404)
    calendar_sync.check_approved(item)
    action = item.action
    db.rollback()
    return call(owner_id, TOOLS[action], proposal_id=str(proposal_id))



def local_operation(db, owner_id, data):
    proposed = call(owner_id, "propose_revision_session", data=data.model_dump(mode="json"))
    identifier = UUID(proposed["id"])
    action = calendar_sync.approve(db, owner_id, identifier)
    return call(owner_id, TOOLS[action], proposal_id=str(identifier))["session"]


@router.post("/sessions", status_code=201, response_model=SessionView)
def create_local(data: PlanInput, request_id: UUID, owner: Owner, db: DB):
    return local_operation(db, owner.id, ProposalInput(request_id=request_id, action="create", plan=data))


@router.patch("/sessions/{identifier}", response_model=SessionView)
def edit_local(identifier: UUID, data: PlanInput, request_id: UUID, owner: Owner, db: DB):
    return local_operation(db, owner.id, ProposalInput(request_id=request_id, action="update", session_id=identifier, plan=data))


@router.delete("/sessions/{identifier}", response_model=SessionView)
def cancel_local(identifier: UUID, request_id: UUID, owner: Owner, db: DB):
    return local_operation(db, owner.id, ProposalInput(request_id=request_id, action="cancel", session_id=identifier))
