from datetime import date, datetime
from typing import Annotated, Generic, TypeVar
from uuid import UUID

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from app.ai.llm import TutorError
from app.db.session import SessionLocal
from app.schemas.planner import Availability, ProposalInput, ProposalView, Recommendation, SessionView
from app.services import calendar_sync, revision_engine

T = TypeVar("T")


class Problem(BaseModel):
    code: str
    message: str
    status: int


class Outcome(BaseModel, Generic[T]):
    value: T | None = None
    error: Problem | None = None


class SessionPage(BaseModel):
    items: list[SessionView]
    has_more: bool


def server_for(authenticated_owner: UUID | None):
    """Bind MCP identity at the trusted application boundary, never in tool input."""
    server = MCPServer("AI Study Buddy Planner")

    def run(schema, function, *args, **kwargs):
        envelope = Outcome[schema]
        if authenticated_owner is None:
            return envelope(error=Problem(code="unauthenticated", message="Authentication required.", status=401))
        try:
            with SessionLocal() as db:
                return envelope(value=function(db, authenticated_owner, *args, **kwargs))
        except TutorError as error:
            return envelope(error=Problem(code=error.code, message=str(error), status=error.status))

    @server.tool(description="Return revision recommendations computed from the signed-in student's graded quizzes.")
    def get_revision_recommendations() -> Outcome[list[Recommendation]]:
        return run(list[Recommendation], revision_engine.recommendations)

    @server.tool(description="List owned revision sessions, optionally limited to a timezone-aware date range.")
    def list_revision_sessions(start: datetime | None = None, end: datetime | None = None,
                               offset: Annotated[int, Field(ge=0, le=20000)] = 0) -> Outcome[SessionPage]:
        return run(SessionPage, revision_engine.list_sessions, start, end, offset=offset)

    @server.tool(description="Suggest study slots using local sessions, with an optional check of the selected Google calendar.")
    def get_calendar_availability(first: date, last: date, duration: Annotated[int, Field(ge=15, le=180)] | None = None,
                                  google: bool = False) -> Outcome[Availability]:
        return run(Availability, revision_engine.available, first, last, duration, google)

    @server.tool(description="Create a pending proposal. No external calendar write is performed.")
    def propose_revision_session(data: ProposalInput) -> Outcome[ProposalView]:
        return run(ProposalView, calendar_sync.propose, data)

    @server.tool(description="Create a session from its server-approved proposal, including Google only when approved.")
    def create_revision_session(proposal_id: UUID) -> Outcome[ProposalView]:
        return run(ProposalView, calendar_sync.execute, proposal_id, "create")

    @server.tool(description="Synchronize an existing owned session using its exact, server-approved destination and details.")
    def sync_revision_session(proposal_id: UUID) -> Outcome[ProposalView]:
        return run(ProposalView, calendar_sync.execute, proposal_id, "sync")

    @server.tool(description="Reschedule an owned session using a server-approved proposal.")
    def reschedule_revision_session(proposal_id: UUID) -> Outcome[ProposalView]:
        return run(ProposalView, calendar_sync.execute, proposal_id, "update")

    @server.tool(description="Cancel an approved owned session and remove its linked event only if approved.")
    def cancel_revision_session(proposal_id: UUID) -> Outcome[ProposalView]:
        return run(ProposalView, calendar_sync.execute, proposal_id, "cancel")

    return server
