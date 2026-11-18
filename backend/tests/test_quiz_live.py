import os
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.quiz import QuizQuestion
from app.services.quiz_attempts import questions
from test_document_flow import ROOT, account, run_one, upload
from test_pdf_processor import make_pdf
from test_quizzes import API, FACTS


def test_live_free_quiz():
    if os.getenv("RUN_LIVE_QUIZ_TEST") != "1" or not os.getenv("DOCUMENT_TEST_DATABASE_URL"):
        pytest.skip("Explicit Free-tier live-test opt-in and a disposable PostgreSQL database required.")
    settings = get_settings()
    assert settings.gemini_free_tier_confirmed and settings.gemini_api_key
    assert os.getenv("DOCUMENT_CLOUD_TEST_BUCKET") == settings.supabase_storage_bucket
    source = make_pdf("Operating Systems", FACTS + (
        " Preventing any one necessary condition prevents deadlock. A total ordering of resource acquisition "
        "prevents circular wait. Requiring all resources up front prevents hold and wait. A circular chain may "
        "occur when process A holds lock 1 and waits for lock 2 while B holds lock 2 and waits for lock 1."
    ))
    with TestClient(app) as client:
        _, owner = account(client)
        document, _ = upload(client, owner, source, "operating-systems.pdf")
        url = f"{ROOT}/{document}"
        try:
            assert run_one(settings).document_id == document
            assert client.get(url, headers=owner).json()["status"] == "READY"
            generated = client.post(API + "/generate", headers=owner, json={
                "document_ids": [str(document)], "request_id": str(uuid4()), "difficulty": "medium",
            }).json()
            assert generated["status"] == "ready", generated.get("error_message")
            quiz_url = API + "/" + generated["id"]
            safe = client.get(quiz_url + "/questions", headers=owner).json()
            assert len(safe) == 5
            assert all(len(set(item["options"])) == 4 and "key" not in item for item in safe)
            started = client.post(quiz_url + "/attempts", headers=owner, json={"request_id": str(uuid4())}).json()
            attempt_url = f"{API}/attempts/{started['id']}"
            with SessionLocal() as db:
                items = questions(db, UUID(generated["id"]))
                assert all(isinstance(item, QuizQuestion) and item.sources[0]["page_number"] == 2 for item in items)
                selected = {str(items[0].id): items[0].key["answer"],
                            str(items[1].id): (items[1].key["answer"] + 1) % 4}
            assert client.patch(attempt_url + "/answers", headers=owner, json={"answers": selected}).status_code == 200
            score = client.post(attempt_url + "/submit", headers=owner).json()
            assert (score["correct"], score["incorrect"], score["unanswered"], score["percentage"]) == (1, 1, 3, 20)
        finally:
            assert client.delete(url, headers=owner).status_code == 202
            assert run_one(settings).document_id == document
        historical = client.get(attempt_url + "/results", headers=owner).json()
        assert historical["percentage"] == 20
        assert all(not item["citations"][0]["available"] for item in historical["questions"])
