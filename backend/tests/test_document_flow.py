from datetime import timedelta
from hashlib import sha256
import os
from uuid import UUID, uuid4

import chromadb
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import inspect, update
from sqlalchemy.exc import IntegrityError

from app.ai import retriever
from app.ai.vector_store import VectorStore, scope
from app.api import documents
from app.core.config import get_settings
from app.db.session import SessionLocal, engine
from app.main import app
from app.models.document import Document, DocumentStatus
from app.services.document_errors import DocumentError
from app import document_worker as worker
from test_pdf_processor import make_pdf

pytestmark = pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL test database required")


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.fail_delete = False

    def ensure_private(self):
        pass

    def upload(self, key, source, size, checksum):
        source.seek(0)
        data = source.read()
        assert len(data) == size and sha256(data).hexdigest() == checksum
        old = self.objects.setdefault(key, data)
        if old != data:
            raise DocumentError("Different PDF already present.", 409)

    def download(self, key, size):
        if key not in self.objects:
            raise DocumentError("Missing object", 404)
        return self.objects[key]

    def delete(self, key):
        if self.fail_delete:
            raise DocumentError("Temporary storage failure.", retryable=True)
        self.objects.pop(key, None)


class FixtureEmbeddings:
    def __init__(self, dimension):
        self.dimension = dimension

    def embed(self, texts, *, query=False):
        return [
            [1.0, 0.0] + [0.0] * (self.dimension - 2) if "normalization" in text.lower()
            else [0.0, 1.0] + [0.0] * (self.dimension - 2)
            for text in texts
        ]


@pytest.fixture
def integration(monkeypatch):
    command.upgrade(Config("alembic.ini"), "head")
    settings = get_settings().model_copy(update={"embedding_batch_size": 1, "document_max_attempts": 2})
    store = VectorStore(chromadb.EphemeralClient(), settings)
    storage = MemoryStorage()
    embedder = FixtureEmbeddings(settings.gemini_embedding_dimensions)
    monkeypatch.setattr(documents, "get_storage", lambda: storage)
    monkeypatch.setattr(worker, "get_storage", lambda: storage)
    monkeypatch.setattr(worker, "get_embeddings", lambda: embedder)
    monkeypatch.setattr(worker, "get_vector_store", lambda: store)
    monkeypatch.setattr(retriever, "get_embeddings", lambda: embedder)
    monkeypatch.setattr(retriever, "get_vector_store", lambda: store)
    with TestClient(app) as client:
        yield client, settings, store, storage


def account(client):
    email = f"{uuid4().hex}@example.com"
    password = "Integration-fixture-pass-481!"
    user = client.post("/api/v1/auth/register", json={"name": "Student", "email": email, "password": password})
    assert user.status_code == 201, user.text
    login = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200
    return UUID(user.json()["id"]), {"Authorization": "Bearer " + login.json()["access_token"]}


ROOT = "/api/v1/documents"


def initialize(client, auth, data, filename="notes.pdf"):
    response = client.post(ROOT + "/uploads/init", headers=auth, json={
        "filename": filename, "content_type": "application/pdf", "file_size": len(data),
    })
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, auth, data, name="notes.pdf"):
    paths = initialize(client, auth, data, name)
    content_type = {**auth, "Content-Type": "application/pdf"}
    assert client.put(paths["upload_path"], headers=content_type, content=data).status_code == 200
    assert client.post(paths["complete_path"], headers=auth).status_code == 202
    return UUID(paths["document"]["id"]), paths


def run_one(settings, clock=worker.now):
    with SessionLocal() as db:
        job = worker.claim(db, settings, clock=clock)
        assert job
        worker.process(db, job, settings, clock=clock)
        return job


def test_authenticated_lifecycle_isolation_retries_and_deletion(integration, monkeypatch):
    client, settings, vectors, storage = integration
    schema = inspect(engine)
    assert {fk["referred_table"] for fk in schema.get_foreign_keys("documents")} == {"users", "subjects"}
    assert "ck_documents_ready" in {rule["name"] for rule in schema.get_check_constraints("documents")}
    assert client.get(ROOT).status_code == 401
    owner, auth = account(client)
    other, other_auth = account(client)
    assert client.get(ROOT, headers={**auth, "Authorization": "Bearer invalid"}).status_code == 401

    payload = {"filename": "notes.pdf", "content_type": "application/pdf", "file_size": 100}
    wrong_type = client.post(ROOT + "/uploads/init", headers=auth, json={**payload, "content_type": "image/png"})
    assert wrong_type.status_code == 415
    too_large = client.post(ROOT + "/uploads/init", headers=auth, json={**payload, "file_size": 200 * 1024 * 1024})
    assert too_large.status_code == 413
    attempted_owner = client.post(ROOT + "/uploads/init", headers=auth, json={**payload, "user_id": str(other)})
    assert attempted_owner.status_code == 422

    content = make_pdf("Normalization organizes relational tables.", "Scheduling improves study sessions.")
    paths = initialize(client, auth, content, "../Principles.PDF")
    assert paths["document"]["filename"] == "Principles.pdf"
    document_id = UUID(paths["document"]["id"])
    url = f"{ROOT}/{document_id}"
    assert "storage_key" not in paths["document"] and "user_id" not in paths["document"]
    assert client.post(paths["complete_path"], headers=auth).status_code == 409
    pdf_headers = {**auth, "Content-Type": "application/pdf"}
    assert client.put(paths["upload_path"], headers=pdf_headers, content=b"x" * len(content)).status_code == 415
    assert client.put(paths["upload_path"], headers=pdf_headers, content=content[:-1]).status_code == 400
    for _ in range(2):
        assert client.put(paths["upload_path"], headers=pdf_headers, content=content).status_code == 200
    assert client.post(paths["complete_path"], headers=auth).status_code == 202
    assert client.post(paths["complete_path"], headers=auth).status_code == 202

    for method, route in [
        ("GET", url), ("GET", url + "/download"), ("POST", url + "/retry"),
        ("DELETE", url), ("POST", paths["complete_path"]), ("PUT", paths["upload_path"]),
    ]:
        assert client.request(method, route, headers=other_auth).status_code == 404
    assert client.get(ROOT, headers=other_auth).json()["items"] == []
    with SessionLocal() as db:
        row = db.get(Document, document_id)
        assert row.storage_key == f"users/{owner}/documents/{document_id}/original.pdf"
        db.add(Document(user_id=owner, filename="copy.pdf", storage_key=row.storage_key, content_type="application/pdf", file_size=4))
        with pytest.raises(IntegrityError):
            db.commit()

    original_upsert = vectors.upsert
    count = 0

    def failing_upsert(*args):
        nonlocal count
        count += 1
        if count == 2:
            raise DocumentError("Temporary index failure.", retryable=True)
        return original_upsert(*args)

    monkeypatch.setattr(vectors, "upsert", failing_upsert)
    assert run_one(settings).document_id == document_id
    assert client.get(url, headers=auth).json()["status"] == "UPLOADED"
    with SessionLocal() as db:
        assert worker.claim(db, settings) is None
        assert retriever.retrieve(db, owner_id=owner, query="normalization") == []

    monkeypatch.setattr(vectors, "upsert", original_upsert)
    future = lambda: worker.now() + timedelta(seconds=31)
    assert run_one(settings, future).document_id == document_id
    ready = client.get(url, headers=auth).json()
    assert (ready["status"], ready["page_count"], ready["chunk_count"]) == ("READY", 2, 2)
    listing = client.get(ROOT, headers=auth, params={"search": "CiPl", "status": "READY", "page_size": 1})
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == str(document_id)
    assert client.get(ROOT, headers=auth, params={"page": 2, "page_size": 1, "sort": "oldest"}).json()["items"] == []
    download = client.get(url + "/download", headers=auth)
    assert download.content == content and "attachment" in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "private, no-store"
    assert client.get(url + "/download", headers=other_auth).status_code == 404

    collection = vectors.client.get_collection(vectors.name, embedding_function=None)
    indexed = collection.get(where=scope(owner, [document_id]), include=["metadatas"])
    assert len(indexed["ids"]) == 2
    assert all(item["owner_id"] == str(owner) and item["embedding_model"] for item in indexed["metadatas"])
    with SessionLocal() as db:
        retrieved = retriever.retrieve(db, owner_id=owner, query="normalization", top_k=1)
        assert (retrieved[0].filename, retrieved[0].page_number) == ("Principles.pdf", 1)
        assert retrieved[0].reference in indexed["ids"]
        assert retriever.retrieve(db, owner_id=other, query="normalization") == []
        with pytest.raises(DocumentError) as failure:
            retriever.retrieve(db, owner_id=other, query="normalization", document_ids=[document_id])
        assert failure.value.status == 404

    assert client.delete(url, headers=auth).status_code == 202
    assert client.get(url + "/download", headers=auth).status_code == 409
    storage.fail_delete = True
    assert run_one(settings).document_id == document_id
    assert client.get(url, headers=auth).json()["status"] == "DELETING"
    with SessionLocal() as db:
        assert retriever.retrieve(db, owner_id=owner, query="normalization") == []
    assert not collection.get(where=scope(owner, [document_id]), include=[])["ids"]
    assert run_one(settings, future).document_id == document_id
    assert client.get(url, headers=auth).json()["retryable"]
    assert client.delete(url, headers=auth).status_code == 202
    storage.fail_delete = False
    assert run_one(settings).document_id == document_id
    assert client.get(url, headers=auth).status_code == 404
    assert not storage.objects


def test_reclaims_abandoned_lease_and_rejects_stale_worker(integration, monkeypatch):
    client, settings, vectors, _ = integration
    _, auth = account(client)
    document_id, _ = upload(client, auth, make_pdf("Revision foundations."))
    with SessionLocal() as db:
        abandoned = worker.claim(db, settings)
        assert abandoned.document_id == document_id
        assert worker.claim(db, settings) is None
    clock = lambda: abandoned.lease + timedelta(seconds=1)
    with SessionLocal() as db:
        reclaimed = worker.claim(db, settings, clock=clock)
        assert reclaimed.attempt == 2
        worker.process(db, abandoned, settings, clock=clock)
        assert client.get(f"{ROOT}/{document_id}", headers=auth).json()["status"] == "PROCESSING"

        original_upsert = vectors.upsert

        def assert_locked(*args):
            with SessionLocal() as contender:
                assert worker.claim(contender, settings, clock=lambda: reclaimed.lease + timedelta(seconds=1)) is None
            assert client.delete(f"{ROOT}/{document_id}", headers=auth).status_code == 409
            return original_upsert(*args)

        monkeypatch.setattr(vectors, "upsert", assert_locked)
        worker.process(db, reclaimed, settings, clock=clock)
    assert client.get(f"{ROOT}/{document_id}", headers=auth).json()["status"] == "READY"
    assert client.delete(f"{ROOT}/{document_id}", headers=auth).status_code == 202
    assert run_one(settings).document_id == document_id


def test_permanent_validation_and_expired_upload_cleanup(integration):
    client, settings, _, _ = integration
    _, auth = account(client)
    document_id, _ = upload(client, auth, make_pdf(""))
    run_one(settings)
    url = f"{ROOT}/{document_id}"
    response = client.get(url, headers=auth).json()
    assert response["status"] == "FAILED"
    assert "OCR" in response["error_message"] and not response["retryable"]
    assert client.post(url + "/retry", headers=auth).status_code == 409
    assert client.delete(url, headers=auth).status_code == 202
    run_one(settings)

    paths = initialize(client, auth, make_pdf("An abandoned upload."))
    pending = UUID(paths["document"]["id"])
    with SessionLocal.begin() as db:
        db.execute(update(Document).where(Document.id == pending).values(
            created_at=worker.now() - timedelta(hours=settings.upload_expiry_hours + 1),
        ))
    assert run_one(settings).document_id == pending
    assert client.get(f"{ROOT}/{pending}", headers=auth).status_code == 404


def test_manual_retry_recovers_exhausted_provider_failures(integration, monkeypatch):
    client, settings, vectors, _ = integration
    _, auth = account(client)
    document_id, _ = upload(client, auth, make_pdf("Retryable ingestion."))
    url = f"{ROOT}/{document_id}"
    original = vectors.upsert

    def unavailable(*args):
        raise DocumentError("Temporary index failure.", retryable=True)

    monkeypatch.setattr(vectors, "upsert", unavailable)
    run_one(settings)
    run_one(settings, lambda: worker.now() + timedelta(seconds=31))
    failed = client.get(url, headers=auth).json()
    assert failed["status"] == "FAILED" and failed["retryable"]
    assert client.post(url + "/retry", headers=auth).status_code == 202
    monkeypatch.setattr(vectors, "upsert", original)
    run_one(settings)
    assert client.get(url, headers=auth).json()["status"] == "READY"
    assert client.delete(url, headers=auth).status_code == 202
    run_one(settings)
