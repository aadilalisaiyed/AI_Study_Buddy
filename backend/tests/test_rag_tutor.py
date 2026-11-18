import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.ai import rag_service
from app.ai.llm import AnswerSection, Generation, ModelAnswer, TutorError
from app.ai.prompts import TUTOR_PROMPT
from app.ai.retriever import RetrievedChunk
from app.api import chat, documents
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.conversation import ChatUsage
from app.models.document import Document
from app.services import conversation_service
from test_document_flow import integration, account, run_one, upload, ROOT
from test_pdf_processor import make_pdf

CHAT = "/api/v1/chat/conversations"
FACTS = "Deadlock needs mutual exclusion, hold and wait, no preemption, and circular wait."


def test_context_budget_deduplicates_and_treats_sources_as_data():
    source = RetrievedChunk(uuid4(), "operating-systems.pdf", 2, FACTS, 0.02, "fixture")
    payload, sources = rag_service.prepare_context("Explain deadlock.", [], [source, source], 1500)
    assert list(sources) == ["S1"]
    assert json.loads(payload)["sources"][0]["page"] == 2
    assert len(TUTOR_PROMPT.encode()) + len(payload.encode()) <= 1500
    assert "untrusted" in TUTOR_PROMPT
    with pytest.raises(TutorError, match="context budget"):
        rag_service.prepare_context("λ" * 900, [], [source], 1500)


def test_unverified_model_references_are_excluded(monkeypatch):
    owner, identifier = uuid4(), uuid4()
    source = RetrievedChunk(identifier, "notes.pdf", 1, FACTS, 0.0, "real")
    monkeypatch.setattr(rag_service, "retrieve", lambda *args, **kwargs: [source])
    class DB:
        def rollback(self):
            pass
    class Tutor:
        def generate(self, payload):
            return Generation(ModelAnswer(insufficient=False, sections=[AnswerSection(text="Claim", sources=["S99"])]), "fixture", {})
    monkeypatch.setattr(rag_service, "get_tutor", Tutor)
    answer = rag_service.answer_question(DB(), owner_id=owner, documents=[identifier],
                                        question="What is deadlock?", history=[], settings=get_settings())
    assert answer.content == rag_service.INSUFFICIENT and answer.citations == []


@pytest.mark.skipif(not __import__("os").getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_authenticated_rag_history_isolation_rate_limit_and_deletion(integration, monkeypatch):
    client, worker_settings, _, _ = integration
    owner, auth = account(client)
    other, other_auth = account(client)
    document, _ = upload(client, auth, make_pdf("Operating Systems", FACTS), "operating-systems.pdf")
    run_one(worker_settings)
    second, _ = upload(client, other_auth, make_pdf("A foreign source says nothing about deadlock."), "second.pdf")
    run_one(worker_settings)
    settings = get_settings().model_copy(update={"chat_requests_per_minute": 2})
    monkeypatch.setattr(conversation_service, "get_settings", lambda: settings)
    contexts = []

    class Tutor:
        def generate(self, payload):
            data = json.loads(payload)
            contexts.append(data)
            relevant = next(source for source in data["sources"] if "mutual exclusion" in source["text"])
            text = FACTS if len(contexts) == 1 else "For example, two processes could each wait for the other’s lock."
            return Generation(ModelAnswer(insufficient=False, sections=[AnswerSection(
                text=text, sources=[relevant["id"]],
            )]), "fixture", {"input": 200})

    monkeypatch.setattr(rag_service, "get_tutor", Tutor)
    assert client.get(CHAT).status_code == 401
    assert client.post(CHAT, headers=other_auth, json={"document_ids": [str(document)]}).status_code == 404
    assert client.post(CHAT, headers=auth, json={"document_ids": [str(second)]}).status_code == 404
    created = client.post(CHAT, headers=auth, json={"document_ids": [str(document)]})
    assert created.status_code == 201, created.text
    url = CHAT + "/" + created.json()["id"]
    other_conversation = client.post(CHAT, headers=other_auth, json={"document_ids": [str(second)]})
    assert other_conversation.status_code == 201
    for method, path, body in [
        ("GET", url, None), ("GET", url + "/messages", None), ("PATCH", url, {"title": "steal"}), ("DELETE", url, None),
    ]:
        assert client.request(method, path, headers=other_auth, json=body).status_code == 404
    assert client.get(ROOT + f"/{document}/download", headers=other_auth).status_code == 404

    request = {"request_id": str(uuid4()), "content": "What are the four conditions for deadlock?", "document_ids": [str(document)]}
    result = client.post(url + "/messages", headers=auth, json=request)
    assert result.status_code == 200, result.text
    answer = result.json()[1]
    assert all(term in answer["content"] for term in ("mutual exclusion", "hold and wait", "no preemption", "circular wait"))
    assert len(answer["citations"]) == 1
    source = answer["citations"][0]
    assert source["document_id"] == str(document) and source["page_number"] == 2 and "circular wait" in source["excerpt"]
    replay = client.post(url + "/messages", headers=auth, json=request)
    assert replay.json() == result.json() and len(contexts) == 1

    follow_up = {**request, "request_id": str(uuid4()), "content": "Explain circular wait with a simple example."}
    assert client.post(url + "/messages", headers=auth, json=follow_up).status_code == 200
    assert any("four conditions" in turn["text"] for turn in contexts[1]["previous_turns"])
    rate = client.post(url + "/messages", headers=auth, json={**request, "request_id": str(uuid4())})
    assert rate.status_code == 429 and rate.json()["detail"]["code"] == "rate_limit"
    history = client.get(url + "/messages", headers=auth, params={"limit": 2}).json()
    assert history["next_before"] and len(history["items"]) == 2
    earlier = client.get(url + "/messages", headers=auth, params={"before": history["next_before"]}).json()
    assert earlier["items"][0]["ordinal"] < history["items"][0]["ordinal"]
    assert client.get(url, headers=auth).json()["document_ids"] == [str(document)]
    assert client.patch(url, headers=auth, json={"title": "Systems revision"}).json()["title"] == "Systems revision"

    assert client.delete(ROOT + f"/{document}", headers=auth).status_code == 202
    run_one(worker_settings)
    history = client.get(url + "/messages", headers=auth).json()["items"]
    assert not history[1]["citations"][0]["available"]
    assert history[1]["citations"][0]["excerpt"] is None
    assert client.post(url + "/messages", headers=auth, json={**request, "request_id": str(uuid4())}).status_code == 404
    assert client.delete(url, headers=auth).status_code == 204
    with SessionLocal() as db:
        assert len(db.scalars(select(ChatUsage).where(ChatUsage.user_id == owner)).all()) == 2
    assert client.delete(ROOT + f"/{second}", headers=other_auth).status_code == 202
    run_one(worker_settings)


@pytest.mark.skipif(not __import__("os").getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_storage_reservations_and_checksum_regression(integration, monkeypatch):
    client, _, _, store = integration
    owner, auth = account(client)
    config = get_settings().model_copy(update={"max_documents_per_user": 1, "total_document_storage_mb": 1})
    monkeypatch.setattr(documents, "get_settings", lambda: config)
    payload = {"filename": "notes.pdf", "content_type": "application/pdf", "file_size": 1024 * 1024}
    first = client.post(ROOT + "/uploads/init", headers=auth, json=payload)
    assert first.status_code == 201
    assert client.post(ROOT + "/uploads/init", headers=auth, json=payload).status_code == 429
    _, other_auth = account(client)
    assert client.post(ROOT + "/uploads/init", headers=other_auth, json=payload).status_code == 429
    url = ROOT + "/" + first.json()["document"]["id"]
    assert client.delete(url, headers=auth).status_code == 202
    run_one(get_settings())
    data = make_pdf(FACTS)
    created = client.post(ROOT + "/uploads/init", headers=auth, json={**payload, "file_size": len(data)})
    paths = created.json()
    assert client.put(paths["upload_path"], headers={**auth, "Content-Type": "application/pdf"}, content=data).status_code == 200
    key = next(iter(store.objects))
    assert str(owner) in key
    store.objects[key] = data[:-1] + b"x"
    assert client.post(paths["complete_path"], headers=auth).status_code == 422
    assert client.delete(ROOT + "/" + paths["document"]["id"], headers=auth).status_code == 202
    run_one(get_settings())
