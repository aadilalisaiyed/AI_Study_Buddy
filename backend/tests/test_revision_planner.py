import base64
from datetime import date, time, timedelta, timezone
from hashlib import sha256
import os
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from anyio import run
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from mcp import Client
import pytest
from sqlalchemy import select

from app.api import integrations
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.mcp.server import server_for
from app.models.planner import CalendarConnection, OAuthState
from app.services import calendar_sync, google_calendar, google_oauth, revision_engine
from app.services.conversation_service import now
from app.services.google_calendar import GoogleError
from test_document_flow import account, integration, run_one, upload
from test_pdf_processor import make_pdf
from test_quizzes import FACTS, questions_for

GOOGLE = "/api/v1/integrations/google"
PLANNER = "/api/v1/planner"
skipdb = pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")


class FakeGoogle:
    def __init__(self):
        self.events = {}
        self.exchanges = []
        self.writes = []
        self.revoke_count = 0
        self.invalid_refresh = False
        self.unavailable = False
        self.lost = False
        self.blocked = []

    def tokens(self, **data):
        self.exchanges.append(data)
        if data["grant_type"] == "refresh_token" and self.invalid_refresh:
            raise GoogleError(400, "Google authorization has expired.", code="calendar_reconnect")
        return {"access_token": "fixture-access", "refresh_token": "fixture-refresh",
                "scope": " ".join(google_calendar.REQUIRED), "expires_in": 3600, "token_type": "Bearer"}

    def userinfo(self, token):
        assert token == "fixture-access"
        return {"sub": "synthetic-identity", "email": "fixture@example.com", "email_verified": True}

    def calendars(self, token):
        assert token == "fixture-access"
        return [{"id": "revision-test", "name": "AI Study Buddy Test", "timezone": "Asia/Kolkata", "primary": False}]

    def revoke(self, token):
        assert token == "fixture-refresh"
        self.revoke_count += 1

    def busy(self, token, calendar, start, end, excluding=None):
        assert calendar["id"] == "revision-test"
        return self.blocked

    def event(self, token, calendar, identifier):
        return self.events.get(identifier)

    def create(self, token, calendar, body):
        if self.unavailable:
            raise GoogleError(503)
        assert body["id"] not in self.events
        self.writes.append("create")
        item = {**body, "etag": '"created"'}
        self.events[body["id"]] = item
        if self.lost:
            self.lost = False
            raise GoogleError(503)
        return item

    def update(self, token, calendar, identifier, etag, body):
        assert self.events[identifier]["etag"] == etag
        self.writes.append("update")
        item = {**body, "id": identifier, "etag": '"updated"'}
        self.events[identifier] = item
        return item

    def remove(self, token, calendar, identifier, etag):
        assert self.events[identifier]["etag"] == etag
        self.writes.append("delete")
        self.events.pop(identifier)


@pytest.fixture
def calendar(integration, monkeypatch):
    cfg = get_settings().model_copy(update={
        "google_oauth_client_id": "fixture-client",
        "google_oauth_client_secret": __import__("pydantic").SecretStr("fixture-secret"),
        "calendar_token_encryption_key": __import__("pydantic").SecretStr(Fernet.generate_key().decode()),
    })
    fake = FakeGoogle()
    monkeypatch.setattr(google_calendar, "get_settings", lambda: cfg)
    for module in (google_calendar, google_oauth, revision_engine, calendar_sync, integrations):
        monkeypatch.setattr(module, "provider", lambda: fake)
    return integration[0], fake, cfg


def authorize(client, headers):
    requested = client.post(GOOGLE + "/authorize", headers=headers)
    assert requested.status_code == 200, requested.text
    parsed = urlsplit(requested.json()["url"])
    assert "access_token" not in parsed.query
    launch = client.get(parsed.path + "?" + parsed.query, follow_redirects=False)
    assert launch.status_code == 303
    assert "HttpOnly" in launch.headers["set-cookie"] and "SameSite=lax" in launch.headers["set-cookie"]
    return parse_qs(urlsplit(launch.headers["location"]).query), parsed.path + "?" + parsed.query


def connect(client, headers):
    params, _ = authorize(client, headers)
    result = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "fixture-code"}, follow_redirects=False)
    assert result.headers["location"].endswith("google=connected")
    chosen = client.put(GOOGLE + "/calendar", headers=headers, json={"calendar_id": "revision-test"})
    assert chosen.json()["selected_calendar"]["id"] == "revision-test"


def plan(**updates):
    day = (now() + timedelta(days=3)).date().isoformat()
    return dict(title="Revise deadlock", local_date=day, local_time="18:00", timezone="Asia/Kolkata",
                duration=45, topic="Deadlock", subject="Operating Systems", **updates)


def proposal(client, headers, action, data=None, *, google=False, session=None):
    request = {"request_id": str(uuid4()), "action": action, "google": google, "session_id": session, "plan": data}
    response = client.post(PLANNER + "/proposals", headers=headers, json=request)
    assert response.status_code == 201, response.text
    return response.json()


def approve(client, headers, item):
    return client.post(f"{PLANNER}/proposals/{item['id']}/confirm", headers=headers, json={"approved": True})


def test_timezones_dst_and_midnight():
    india = revision_engine.resolve_local(date(2027, 1, 4), time(23, 45), "Asia/Kolkata")
    assert india.hour == 18 and india.minute == 15
    assert (india + timedelta(minutes=45)).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).day == 5
    assert revision_engine.resolve_local(date(2027, 1, 4), time(12), "UTC").tzinfo is timezone.utc
    with pytest.raises(Exception, match="does not exist"):
        revision_engine.resolve_local(date(2027, 3, 14), time(2, 30), "America/New_York")
    with pytest.raises(Exception, match="occurs twice"):
        revision_engine.resolve_local(date(2027, 11, 7), time(1, 30), "America/New_York")
    a = revision_engine.resolve_local(date(2027, 11, 7), time(1, 30), "America/New_York", 0)
    b = revision_engine.resolve_local(date(2027, 11, 7), time(1, 30), "America/New_York", 1)
    assert b-a == timedelta(hours=1)


@skipdb
def test_oauth_browser_binding_scopes_replay_and_refresh(calendar, monkeypatch):
    client, fake, cfg = calendar
    owner, auth = account(client)
    _, other = account(client)
    assert client.post(GOOGLE + "/authorize").status_code == 401
    params, launch = authorize(client, auth)
    assert params["redirect_uri"] == [cfg.google_oauth_redirect_uri]
    assert params["code_challenge_method"] == ["S256"] and params["access_type"] == ["offline"]
    assert client.get(launch, follow_redirects=False).status_code == 400
    with TestClient(app) as foreign_browser:
        authorize(foreign_browser, other)
        cross = foreign_browser.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "forged"}, follow_redirects=False)
        assert cross.headers["location"].endswith("google=oauth_state") and not fake.exchanges
    callback = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "fixture-code"}, follow_redirects=False)
    assert callback.headers["location"].endswith("google=connected")
    accepted = fake.exchanges[0]
    challenge = base64.urlsafe_b64encode(sha256(accepted["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert params["code_challenge"] == [challenge]
    assert accepted["redirect_uri"] == cfg.google_oauth_redirect_uri
    assert client.get(GOOGLE + "/status", headers=other).json()["status"] == "disconnected"
    assert client.get(GOOGLE + "/calendars", headers=other).status_code == 409
    replay = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "again"}, follow_redirects=False)
    assert replay.headers["location"].endswith("google=oauth_state") and len(fake.exchanges) == 1
    with SessionLocal.begin() as db:
        connection = db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == owner))
        assert connection.encrypted_refresh_token != "fixture-refresh" and connection.encrypted_access_token != "fixture-access"
        connection.access_expires_at = now()-timedelta(seconds=1)
    assert client.get(GOOGLE + "/calendars", headers=auth).status_code == 200
    assert fake.exchanges[-1]["grant_type"] == "refresh_token"
    fake.invalid_refresh = True
    with SessionLocal.begin() as db:
        db.scalar(select(CalendarConnection).where(CalendarConnection.user_id == owner)).access_expires_at = now()-timedelta(seconds=1)
    assert client.get(GOOGLE + "/calendars", headers=auth).status_code == 503
    assert client.get(GOOGLE + "/status", headers=auth).json()["status"] == "reconnect_required"
    assert client.post(GOOGLE + "/disconnect", headers=auth).json()["revoked"]
    assert fake.revoke_count == 1
    params, _ = authorize(client, auth)
    with SessionLocal.begin() as db:
        db.scalar(select(OAuthState).where(OAuthState.user_id == owner)).expires_at = now()-timedelta(seconds=1)
    expired = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "late"}, follow_redirects=False)
    assert expired.headers["location"].endswith("google=oauth_state")
    params, _ = authorize(client, auth)
    denied = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "error": "access_denied"}, follow_redirects=False)
    assert denied.headers["location"].endswith("google=denied")
    params, _ = authorize(client, auth)
    real = fake.tokens
    monkeypatch.setattr(fake, "tokens", lambda **data: {**real(**data), "scope": google_calendar.EVENT_SCOPE})
    missing = client.get(GOOGLE + "/callback", params={"state": params["state"][0], "code": "limited"}, follow_redirects=False)
    assert missing.headers["location"].endswith("google=calendar_scope")
    monkeypatch.setattr(google_calendar, "get_settings", lambda: cfg.model_copy(update={"google_oauth_redirect_uri": "http://evil.invalid/callback"}))
    assert client.post(GOOGLE + "/authorize", headers=auth).status_code == 503


@skipdb
def test_mcp_approval_sync_retry_and_isolation(calendar):
    client, fake, _ = calendar
    owner, auth = account(client)
    foreign, other = account(client)
    connect(client, auth)
    first = proposal(client, auth, "create", plan(), google=True)
    identifier = first["id"]

    async def inspect_protocol():
        async with Client(server_for(owner)) as session:
            tools = await session.list_tools()
            assert {item.name for item in tools.tools} == {
                "get_revision_recommendations", "list_revision_sessions", "get_calendar_availability",
                "propose_revision_session", "create_revision_session", "sync_revision_session",
                "reschedule_revision_session", "cancel_revision_session",
            }
            assert all(item.input_schema and item.output_schema for item in tools.tools)
            empty = await session.call_tool("list_revision_sessions")
            assert empty.structured_content["value"]["items"] == []
            invalid = await session.call_tool("create_revision_session", {"proposal_id": "not-a-uuid"})
            assert invalid.is_error
            denied = await session.call_tool("create_revision_session", {"proposal_id": identifier})
            assert denied.structured_content["error"]["code"] == "confirmation_required"
        async with Client(server_for(foreign)) as session:
            result = await session.call_tool("create_revision_session", {"proposal_id": identifier})
            assert result.structured_content["error"]["status"] == 404
        async with Client(server_for(None)) as session:
            result = await session.call_tool("list_revision_sessions")
            assert result.structured_content["error"]["status"] == 401

    run(inspect_protocol)
    assert not fake.writes
    assert approve(client, other, first).status_code == 404
    assert client.post(f"{PLANNER}/proposals/{identifier}/confirm", headers=auth, json={"approved": False}).status_code == 422
    fake.lost = True
    result = approve(client, auth, first).json()
    assert result["status"] == "failed" and result["session"]["sync_status"] == "sync_failed"
    identifier_session = result["session_id"]
    assert len(fake.events) == 1 and fake.writes == ["create"]
    assert client.get(f"{PLANNER}/sessions/{identifier_session}", headers=other).status_code == 404
    replay = client.post(f"{PLANNER}/sessions/{identifier_session}/sync", params={"proposal_id": identifier},
                         headers=auth, json={"approved": True}).json()
    assert replay["status"] == "done" and replay["session"]["sync_status"] == "synced"
    assert len(fake.events) == 1 and fake.writes == ["create"]
    assert approve(client, auth, first).json()["session_id"] == identifier_session
    second = proposal(client, auth, "update", {**plan(), "local_time": "19:30"}, google=True, session=identifier_session)
    assert fake.writes == ["create"]
    assert approve(client, auth, second).json()["session"]["sync_status"] == "synced"
    assert fake.writes == ["create", "update"]
    cancel = proposal(client, auth, "cancel", google=True, session=identifier_session)
    assert fake.writes == ["create", "update"]
    assert approve(client, auth, cancel).json()["session"]["status"] == "cancelled"
    assert not fake.events and fake.writes == ["create", "update", "delete"]
    assert client.post(GOOGLE + "/disconnect", headers=auth).status_code == 200
    assert client.get(f"{PLANNER}/sessions/{identifier_session}", headers=auth).json()["status"] == "cancelled"


@skipdb
def test_local_preferences_conflicts_completion_and_availability(calendar):
    client, fake, _ = calendar
    _, auth = account(client)
    _, foreign = account(client)
    initial = client.get(PLANNER + "/preferences", headers=auth).json()
    updated = {**initial, "duration": 40, "break_minutes": 20, "timezone": "Asia/Kolkata"}
    assert client.put(PLANNER + "/preferences", headers=auth, json=updated).json()["duration"] == 40
    assert client.get(PLANNER + "/preferences", headers=foreign).json()["duration"] == 45
    start = plan()["local_date"]
    assert client.get(PLANNER + "/availability", headers=auth, params={"first": start, "last": start}).json()["scope"] == "local"
    one = proposal(client, auth, "create", plan())
    done = approve(client, auth, one).json()
    assert done["session"]["sync_status"] == "local_only" and not fake.writes
    identifier = done["session_id"]
    overlap = client.post(PLANNER + "/proposals", headers=auth, json={
        "request_id": str(uuid4()), "action": "create", "plan": {**plan(), "local_time": "18:55"},
    })
    assert overlap.status_code == 409
    changed = proposal(client, auth, "update", {**plan(), "local_time": "20:00"}, session=identifier)
    assert approve(client, auth, changed).json()["status"] == "done"
    assert client.post(f"{PLANNER}/sessions/{identifier}/complete", headers=auth).json()["status"] == "completed"
    assert client.get(f"{PLANNER}/sessions/{identifier}", headers=foreign).status_code == 404
    connect(client, auth)
    fake.blocked = [(now()-timedelta(days=1), now()+timedelta(days=10))]
    slots = client.get(PLANNER + "/availability", headers=auth, params={"first": start, "last": start, "google": True})
    assert slots.json()["scope"] == "google" and slots.json()["slots"] == []


@skipdb
def test_recommendation_uses_graded_quiz_rows(integration, monkeypatch):
    from app.ai import quiz_generator
    client, settings, vectors, _ = integration
    _, auth = account(client)
    assert client.get(PLANNER + "/recommendations", headers=auth).json() == []
    document, _ = upload(client, auth, make_pdf("Operating Systems", FACTS), "operating-systems.pdf")
    run_one(settings)
    monkeypatch.setattr(quiz_generator, "get_vector_store", lambda: vectors)

    class FakeQuiz:
        def generate_structured(self, payload, *args, **kwargs):
            import json
            source = next(item for item in json.loads(payload)["passages"] if "mutual exclusion" in item["text"])
            return questions_for(source["label"], "mutual exclusion, hold and wait"), {}

    monkeypatch.setattr(quiz_generator, "get_tutor", FakeQuiz)
    quiz = client.post("/api/v1/quizzes/generate", headers=auth, json={
        "request_id": str(uuid4()), "document_ids": [str(document)],
    }).json()
    attempt = client.post(f"/api/v1/quizzes/{quiz['id']}/attempts", headers=auth, json={"request_id": str(uuid4())}).json()
    endpoint = f"/api/v1/quizzes/attempts/{attempt['id']}"
    values = {item["id"]: (item["options"].index("Mutual exclusion")+1)%4 for item in attempt["questions"][:3]}
    client.patch(endpoint + "/answers", headers=auth, json={"answers": values})
    assert client.post(endpoint + "/submit", headers=auth).json()["earned"] == 0
    result = client.get(PLANNER + "/recommendations", headers=auth).json()
    assert [(item["topic"], item["subject"], item["samples"]) for item in result] == [("Deadlock", "Operating Systems", 3)]
    assert result[0]["document_ids"] == [str(document)] and result[0]["source_quiz_id"] == quiz["id"]
    assert client.delete("/api/v1/documents/" + str(document), headers=auth).status_code == 202
    run_one(settings)


@skipdb
def test_failed_create_keeps_local_session_and_remote_edit_is_not_overwritten(calendar):
    client, fake, _ = calendar
    _, auth = account(client)
    connect(client, auth)
    initial = proposal(client, auth, "create", plan(), google=True)
    fake.unavailable = True
    failed = approve(client, auth, initial).json()
    identifier = failed["session_id"]
    assert failed["status"] == "failed" and not fake.events
    history = client.get(f"{PLANNER}/sessions/{identifier}", headers=auth).json()
    assert history["status"] == "scheduled" and history["sync_retry_id"] == initial["id"]
    fake.unavailable = False
    synced = approve(client, auth, initial).json()
    assert synced["status"] == "done"
    key = next(iter(fake.events))
    prior = fake.events[key]["start"]
    fake.events[key]["etag"] = '"external-user-change"'
    reviewed = proposal(client, auth, "update", {**plan(), "local_time": "20:00"},
                        google=True, session=identifier)
    rejected = approve(client, auth, reviewed).json()
    assert rejected["status"] == "failed" and "changed in Google" in rejected["error"]
    assert fake.writes == ["create"] and fake.events[key]["start"] == prior
    assert rejected["session"]["start_at"] != synced["session"]["start_at"]
