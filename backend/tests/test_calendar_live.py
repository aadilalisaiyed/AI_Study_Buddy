from datetime import timedelta
import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.main import app
from app.services.conversation_service import now
from app.services.google_calendar import access, connection, provider
from app.services.revision_engine import event_link
from test_revision_planner import GOOGLE, PLANNER, approve, proposal


def test_explicitly_approved_dedicated_google_calendar():
    if os.getenv("RUN_LIVE_CALENDAR_TEST") != "1" or not os.getenv("DOCUMENT_TEST_DATABASE_URL"):
        pytest.skip("An isolated OAuth-connected local application account and explicit live opt-in are required.")
    jwt = os.environ["PLANNER_LIVE_JWT"]
    owner = decode_access_token(jwt)
    expected = os.environ["GOOGLE_CALENDAR_TEST_ID"]
    headers = {"Authorization": f"Bearer {jwt}"}
    with TestClient(app) as client:
        status = client.get(GOOGLE + "/status", headers=headers).json()
        selected = status["selected_calendar"]
        assert selected["id"] == expected and not selected["primary"] and selected["name"] == "AI Study Buddy Test"
        day = (now() + timedelta(days=7)).date().isoformat()
        available = client.get(PLANNER + "/availability", headers=headers, params={
            "first": day, "last": (now() + timedelta(days=13)).date().isoformat(), "google": True,
        }).json()
        assert available["scope"] == "google" and len(available["slots"]) >= 2
        first, second = available["slots"][:2]
        title = f"AI Study Buddy integration fixture {uuid4().hex}"
        session_id = None

        def plan(slot):
            return {"title": title, "topic": "Smoke test", "duration": 45, "local_date": slot["local_date"],
                    "local_time": slot["local_time"], "fold": slot["fold"], "timezone": slot["timezone"]}

        def read_event():
            with SessionLocal() as db:
                link = event_link(db, UUID(session_id))
                token = access(db, connection(db, owner))
                return provider().event(token, link.calendar_id, link.event_id)

        try:
            created = approve(client, headers, proposal(client, headers, "create", plan(first), google=True)).json()
            session_id = created["session_id"]
            assert created["status"] == "done" and read_event()["summary"] == title
            updated = approve(client, headers, proposal(client, headers, "update", plan(second),
                                                       session=session_id, google=True)).json()
            assert updated["status"] == "done"
            assert updated["session"]["sync_status"] == "synced"
        finally:
            if session_id:
                cancelled = approve(client, headers, proposal(client, headers, "cancel",
                                                              session=session_id, google=True)).json()
                assert cancelled["status"] == "done" and cancelled["session"]["status"] == "cancelled"
                assert read_event() is None
