from datetime import timedelta
import os
from uuid import uuid4

from pydantic import ValidationError
import pytest
from sqlalchemy import select

from app.ai import quiz_generator as generator
from app.ai.llm import TutorError
from app.ai.retriever import RetrievedChunk
from app.db.session import SessionLocal
from app.models.quiz import QuizAttempt, QuizQuestion, QuizUsage
from app.schemas.quiz import Generate
from app.services.conversation_service import now
from app.services.quiz_grader import grade, percentage
from test_document_flow import ROOT, account, integration, run_one, upload
from test_pdf_processor import make_pdf

API = "/api/v1/quizzes"
FACTS = (
    "Deadlock occurs when processes wait indefinitely for resources. The four necessary conditions for deadlock "
    "are mutual exclusion, hold and wait, no preemption, and circular wait. Mutual exclusion means a resource "
    "has one holder. Hold and wait means keeping resources while requesting more. No preemption means a "
    "held resource cannot be forcibly reclaimed. Circular wait is a closed chain of resource dependencies."
)
PROMPTS = [
    "What condition rules out concurrent use of a non-shareable resource?",
    "Which concept describes requesting more resources while keeping current allocations?",
    "What term means a resource cannot be forcibly reclaimed?",
    "How does a closed dependency chain illustrate deadlock?",
    "What happens to the processes when they deadlock?",
]
OPTIONS = ["Mutual exclusion", "Memory paging", "Interrupt handling", "Time slicing"]


def questions_for(source, evidence, prompts=PROMPTS):
    return generator.Candidates(insufficient=False, questions=[
        generator.Candidate(kind="mcq", difficulty="medium", prompt=prompt, options=OPTIONS,
                            index=0, boolean=None, expected=None, concepts=[], explanation="Mutual exclusion is required.",
                            topic="Deadlock", source=source, evidence=evidence)
        for prompt in prompts
    ])


def test_schema_and_grounding_reject_invalid_batches():
    request = Generate(request_id=uuid4())
    text = "The four necessary conditions for deadlock are mutual exclusion, hold and wait, no preemption, and circular wait."
    source = RetrievedChunk(uuid4(), "notes.pdf", 2, text, 0.1, "real-id")
    good = questions_for("S1", "mutual exclusion, hold and wait")
    rows = generator.validate(good, request, {"S1": source}, [])
    assert rows[0]["options"][rows[0]["key"]["answer"]] == "Mutual exclusion"
    assert rows[0]["sources"][0]["page_number"] == 2
    assert generator.counts("mixed", 5) == {"mcq": 2, "boolean": 2, "short": 1}
    raw = good.questions[0].model_dump()
    with pytest.raises(ValidationError):
        generator.Candidate.model_validate({**raw, "index": True})
    for first in [
        {"options": OPTIONS[:3]}, {"index": 4}, {"options": [OPTIONS[0]] * 4},
        {"source": "S7"}, {"evidence": "The text does not contain any of this."}, {"difficulty": "easy"},
        {"prompt": PROMPTS[1]},
    ]:
        altered = good.model_copy(update={"questions": [good.questions[0].model_copy(update=first), *good.questions[1:]]})
        with pytest.raises(TutorError):
            generator.validate(altered, request, {"S1": source}, [])
    with pytest.raises(TutorError):
        generator.validate(good, request, {"S1": source}, [PROMPTS[0]])


def test_grading_objective_short_and_rounding():
    assert grade("mcq", 0, {"answer": 0})[0] == 1
    assert grade("mcq", False, {"answer": 0})[0] == 0
    assert grade("boolean", False, {"answer": False})[0] == 1
    assert grade("boolean", True, {"answer": False})[0] == 0
    assert grade("mcq", None, {"answer": 1}) == (0, ["Not answered"])
    key = {"concepts": [{"label": "Wait", "phrases": ["circular wait"]},
                        {"label": "Preemption", "phrases": ["no preemption"]}]}
    assert grade("short", "circular wait", key)[0] == 1
    assert grade("short", "No preemption; circular wait.", key)[0] == 2
    assert grade("short", "Circular wait is not required.", key)[0] == 0
    assert percentage(1, 3) == 33.33
    assert percentage(2, 3) == 66.67


@pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_generation_attempts_privacy_weak_practice_and_timer(integration, monkeypatch):
    client, settings, vectors, _ = integration
    owner, headers = account(client)
    _, foreign = account(client)
    document, _ = upload(client, headers, make_pdf("Systems lecture", FACTS), "operating-systems.pdf")
    run_one(settings)
    monkeypatch.setattr(generator, "get_vector_store", lambda: vectors)
    monkeypatch.setattr(generator, "retrieve", lambda *args, **kwargs: [])
    subjects_url = "/api/v1/subjects"
    created_subject = client.post(subjects_url, headers=headers, json={"name": "Operating Systems"})
    assert created_subject.status_code == 201
    subject = created_subject.json()
    assert client.post(subjects_url, headers=headers, json={"name": " operating   SYSTEMS "}).status_code == 409
    assert client.get(subjects_url, headers=foreign).json() == []
    assignment = subjects_url + f"/documents/{document}"
    assert client.put(assignment, headers=foreign, json={"subject_id": subject["id"]}).status_code == 404
    assert client.put(assignment, headers=headers, json={"subject_id": subject["id"]}).status_code == 200
    assert client.get(ROOT, headers=headers, params={"subject_id": subject["id"]}).json()["total"] == 1
    calls = []

    class Model:
        def generate_structured(self, raw, prompt, schema, tokens, **options):
            import json
            payload = json.loads(raw)
            calls.append(payload)
            source = next(item for item in payload["passages"] if "mutual exclusion" in item["text"])
            prompts = PROMPTS if not payload["exclude"] else [
                "Which process property prevents a forced transfer of an allocated resource?",
                "Can two jobs hold an exclusive printer at the same time?",
                "Why does keeping one lock while acquiring a second matter?",
                "What type of dependency is formed when each job waits for its neighbor?",
                "What distinguishes a deadlock from a short delay?",
            ]
            return questions_for(source["label"], "mutual exclusion, hold and wait", prompts), {"output": 400}

    monkeypatch.setattr(generator, "get_tutor", Model)
    payload = {"request_id": str(uuid4()), "document_ids": [str(document)], "minutes": 2, "subject_id": subject["id"]}
    assert client.get(API + "/performance/summary", headers=headers).json()["attempts_completed"] == 0
    assert client.post(API + "/generate", headers=foreign, json=payload).status_code == 404
    response = client.post(API + "/generate", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "ready", response.text
    quiz = response.json()["id"]
    assert client.post(API + "/generate", headers=headers, json=payload).json()["id"] == quiz
    assert len(calls) == 1
    assert client.post(API + "/generate", headers=headers, json={**payload, "kind": "mixed"}).status_code == 409
    safe = client.get(f"{API}/{quiz}/questions", headers=headers).json()
    assert len(safe) == 5 and all(set(q) == {"id","position","kind","prompt","options","max_marks"} for q in safe)
    assert all(len(set(item["options"])) == 4 for item in safe)
    for method, suffix in [("GET", ""), ("GET", "/questions"), ("POST", "/attempts"), ("DELETE", "")]:
        assert client.request(method, API + "/" + quiz + suffix, headers=foreign, json={"request_id": str(uuid4())}).status_code == 404
    assert client.get(f"{ROOT}/{document}/download", headers=foreign).status_code == 404
    start = {"request_id": str(uuid4())}
    starting = client.post(f"{API}/{quiz}/attempts", headers=headers, json=start).json()
    attempt = starting["id"]
    assert client.post(f"{API}/{quiz}/attempts", headers=headers, json=start).json()["id"] == attempt
    url = f"{API}/attempts/{attempt}"
    assert client.get(url + "/results", headers=headers).status_code == 409
    for method, suffix in [("GET", ""), ("PATCH", "/answers"), ("POST", "/submit"), ("GET", "/results")]:
        assert client.request(method, url + suffix, headers=foreign, json={"answers": {}}).status_code == 404
    right = [q["options"].index("Mutual exclusion") for q in safe]
    submitted = {q["id"]: (right[i] + 1) % 4 for i, q in enumerate(safe[:3])}
    submitted[safe[3]["id"]] = right[3]
    assert client.patch(url + "/answers", headers=headers, json={"answers": {safe[0]["id"]: True}}).status_code == 422
    assert client.patch(url + "/answers", headers=headers, json={"answers": submitted}).json()["answers"] == submitted
    assert client.get(url, headers=headers).json()["answers"] == submitted
    scored = client.post(url + "/submit", headers=headers).json()
    assert (scored["earned"], scored["total"], scored["percentage"]) == (1, 5, 20)
    assert (scored["correct"], scored["incorrect"], scored["unanswered"]) == (1, 3, 1)
    assert scored["questions"][0]["citations"][0]["page_number"] == 2
    assert client.post(url + "/submit", headers=headers).json() == scored
    assert client.patch(url + "/answers", headers=headers, json={"answers": submitted}).status_code == 409
    performance = client.get(API + "/performance/summary", headers=headers).json()
    assert performance["attempts_completed"] == 1 and performance["questions_answered"] == 4
    assert performance["accuracy_percent"] == 25 and performance["weak_topics"][0]["label"] == "Deadlock"
    analytics_url = "/api/v1/analytics/overview"
    assert client.get(analytics_url).status_code == 401
    analytics = client.get(analytics_url, headers=headers).json()
    assert analytics["subjects"] == [{"label": "Operating Systems", "quizzes": 1, "average_score": 20}]
    assert analytics["overview"]["attempts"] == 1
    assert analytics["overview"]["quizzes"] == 1
    assert analytics["overview"]["questions"] == 4
    assert analytics["overview"]["accuracy"] == 25
    assert analytics["overview"]["average_score"] == 20
    assert analytics["trend"][0]["score"] == 20
    assert analytics["weak_topics"][0]["label"] == "Deadlock"
    assert analytics["consistency"]["active_days"] == 1
    assert client.get(analytics_url, headers=foreign).json()["overview"]["attempts"] == 0
    assert client.get(analytics_url + "?timezone=invalid", headers=headers).status_code == 422
    assert client.get(analytics_url + "?start_date=2024-03-01&end_date=2024-02-29", headers=headers).status_code == 422
    assert client.delete(subjects_url + "/" + subject["id"], headers=headers).status_code == 204
    assert client.get(analytics_url, headers=headers).json()["subjects"][0]["label"] == "Operating Systems"
    practice = client.post(API + "/generate", headers=headers, json={"request_id": str(uuid4()), "weak_practice": True}).json()
    assert practice["status"] == "ready", practice
    assert calls[-1]["focus"] == "Deadlock" and calls[-1]["exclude"]

    retake = client.post(f"{API}/{quiz}/retake", headers=headers, json={"request_id": str(uuid4())}).json()
    assert retake["id"] != attempt
    from uuid import UUID
    with SessionLocal.begin() as db:
        record = db.get(QuizAttempt, UUID(retake["id"]))
        record.deadline = now() - timedelta(seconds=1)
        assert len(db.scalars(select(QuizQuestion).where(QuizQuestion.quiz_id == UUID(quiz))).all()) == 5
    expired = f"{API}/attempts/{retake['id']}"
    assert client.patch(expired + "/answers", headers=headers, json={"answers": submitted}).status_code == 409
    assert client.get(expired + "/results", headers=headers).json()["unanswered"] == 5
    assert len(client.get(f"{API}/{quiz}/attempts", headers=headers).json()["items"]) == 2
    assert client.delete(f"{ROOT}/{document}", headers=headers).status_code == 202
    run_one(settings)
    historical = client.get(url + "/results", headers=headers).json()
    assert historical["percentage"] == 20 and historical["questions"][0]["citations"][0]["available"] is False
    assert historical["questions"][0]["citations"][0]["chunk_id"] is None
    assert client.delete(f"{API}/{quiz}", headers=headers).status_code == 204
    assert client.get(analytics_url, headers=headers).json()["overview"]["attempts"] == 0
    assert client.post(API + "/generate", headers=headers, json=payload).status_code == 410
    with SessionLocal() as db:
        assert len(db.scalars(select(QuizUsage).where(QuizUsage.user_id == owner)).all()) == 2


@pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_provider_failures_and_shared_quota(integration, monkeypatch):
    client, settings, _, _ = integration
    _, auth = account(client)
    document, _ = upload(client, auth, make_pdf(FACTS), "quota.pdf")
    run_one(settings)
    chat = client.post("/api/v1/chat/conversations", headers=auth, json={}).json()["id"]
    calls = []

    def fail(*args):
        chat_response = client.post(f"/api/v1/chat/conversations/{chat}/messages", headers=auth, json={
            "document_ids": [str(document)], "request_id": str(uuid4()), "content": "Explain circular wait.",
        })
        assert chat_response.status_code == 429 and chat_response.json()["detail"]["code"] == "ai_busy"
        calls.append(1)
        raise TutorError("provider_quota", "Gemini's Free-tier quota is temporarily exhausted.", 429)

    monkeypatch.setattr(generator, "generate", fail)
    payload = {"document_ids": [str(document)], "request_id": str(uuid4())}
    first = client.post(API + "/generate", headers=auth, json=payload).json()
    assert first["status"] == "failed" and "quota" in first["error_message"]
    assert client.post(API + "/generate", headers=auth, json=payload).json()["id"] == first["id"]
    assert client.delete(API + "/" + first["id"], headers=auth).status_code == 204
    for _ in range(2):
        response = client.post(API + "/generate", headers=auth, json={**payload, "request_id": str(uuid4())})
        assert response.json()["status"] == "failed"
    limited = client.post(API + "/generate", headers=auth, json={**payload, "request_id": str(uuid4())})
    assert limited.status_code == 429 and limited.json()["detail"]["code"] == "quiz_quota"
    assert len(calls) == 3
    assert client.delete(f"{ROOT}/{document}", headers=auth).status_code == 202
    run_one(settings)


def test_mixed_configuration_and_source_supported_short_rubric():
    request = Generate(request_id=uuid4(), kind="mixed")
    source = RetrievedChunk(uuid4(), "notes.pdf", 2, FACTS, 0, "real-id")
    mcqs = questions_for("S1", "mutual exclusion, hold and wait").questions[:2]
    boolean = [
        generator.Candidate(kind="boolean", difficulty="medium", prompt="Does circular wait form a closed dependency chain?",
                            boolean=True, explanation="Each process waits on its successor in a cycle.", topic="Deadlock",
                            source="S1", evidence="a closed chain of resource dependencies"),
        generator.Candidate(kind="boolean", difficulty="medium", prompt="Can resources be forcibly reclaimed under no preemption?",
                            boolean=False, explanation="A held resource cannot be forcibly reclaimed.", topic="Deadlock",
                            source="S1", evidence="a held resource cannot be forcibly reclaimed"),
    ]
    short = generator.Candidate(kind="short", difficulty="medium", prompt="Name two conditions necessary for deadlock.",
        expected="Mutual exclusion and hold and wait.", explanation="Both are among the four required conditions.",
        topic="Deadlock", source="S1", evidence="mutual exclusion, hold and wait",
        concepts=[generator.Concept(label="Exclusive resource", phrases=["mutual exclusion"]),
                  generator.Concept(label="Retention", phrases=["hold and wait"])])
    batch = generator.Candidates(insufficient=False, questions=[*mcqs, *boolean, short])
    rows = generator.validate(batch, request, {"S1": source}, [])
    assert [row["kind"] for row in rows] == ["mcq", "mcq", "boolean", "boolean", "short"]
    assert rows[-1]["max_marks"] == 2
    assert grade("short", "mutual exclusion", rows[-1]["key"])[0] == 1
    short.concepts[0].phrases = ["an unrelated concept"]
    with pytest.raises(TutorError):
        generator.validate(batch, request, {"S1": source}, [])
