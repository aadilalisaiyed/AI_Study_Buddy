import os
from uuid import uuid4

import pytest

from test_document_flow import integration

SERVER = "http://127.0.0.1:5173"
BASE = "/api/v1/auth"


@pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_rotating_session_origin_and_replay(integration):
    client, *_ = integration
    user = {"name": "Session Student", "email": f"{uuid4().hex}@example.com", "password": "Session-fixture-pass-766!"}
    assert client.post(BASE+"/register", json=user).status_code == 201
    missing = client.post(BASE+"/login", data={"username": "missing@example.com", "password": "incorrect"})
    wrong = client.post(BASE+"/login", data={"username": user["email"], "password": "incorrect"})
    assert missing.status_code == wrong.status_code == 401
    assert missing.json() == wrong.json()
    login = client.post(BASE+"/login", data={"username": user["email"], "password": user["password"]})
    assert login.status_code == 200
    assert "HttpOnly" in login.headers["set-cookie"]
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    first = client.cookies.get("study_refresh")
    assert client.post(BASE+"/refresh").status_code == 403
    assert client.post(BASE+"/refresh", headers={"Origin": "https://untrusted.example"}).status_code == 403
    refreshed = client.post(BASE+"/refresh", headers={"Origin": SERVER})
    assert refreshed.status_code == 200
    assert client.cookies.get("study_refresh") != first
    assert client.get(BASE+"/me", headers=headers).status_code == 200
    client.cookies.clear()
    client.cookies.set("study_refresh", first)
    assert client.post(BASE+"/refresh", headers={"Origin": SERVER}).status_code == 401
    assert client.get(BASE+"/me", headers=headers).status_code == 401

    client.cookies.clear()
    login = client.post(BASE+"/login", data={"username": user["email"], "password": user["password"]})
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert client.post(BASE+"/logout", headers={"Origin": SERVER}).status_code == 204
    assert client.get(BASE+"/me", headers=headers).status_code == 401


def test_boundary_does_not_echo_private_validation_input():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    marker = "private-input-fixture"
    invalid = client.post(BASE+"/register", json={"name": marker, "email": "invalid", "password": 1234})
    assert invalid.status_code == 422
    assert marker not in invalid.text and "1234" not in invalid.text
    assert invalid.headers["X-Content-Type-Options"] == "nosniff"
    assert invalid.headers["X-Request-ID"]
    assert client.post(BASE+"/register", content=b"x" * (257*1024)).status_code == 413
    assert client.get("/", headers={"Host": "untrusted.example"}).status_code == 400



def test_auth_rate_limit_is_bounded(monkeypatch):
    from fastapi import HTTPException
    from app.services import auth_sessions

    monkeypatch.setattr(auth_sessions, "LIMIT", 2)
    address = uuid4().hex
    auth_sessions.throttle(address, "test")
    auth_sessions.throttle(address, "test")
    with pytest.raises(HTTPException) as error:
        auth_sessions.throttle(address, "test")
    assert error.value.status_code == 429
    auth_sessions.throttle(address, "other")
