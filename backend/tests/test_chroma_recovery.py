import os

import chromadb
import pytest

from app.ai.vector_store import VectorStore
from app.db.session import SessionLocal
from app.document_worker import ingest, now
from app.models.document import Document
from test_document_flow import ROOT, account, integration, run_one, upload
from test_pdf_processor import make_pdf


@pytest.mark.skipif(not os.getenv("DOCUMENT_TEST_DATABASE_URL"), reason="Dedicated PostgreSQL required")
def test_rebuild_from_original_pdf_retains_owner_pages_and_stable_ids(integration, monkeypatch):
    client, settings, original, _ = integration
    owner, headers = account(client)
    other, _ = account(client)
    document, _ = upload(client, headers, make_pdf(
        "First page studies normalization and dependencies.",
        "Second page compares quality and consistency."
    ), "restore.pdf")
    run_one(settings)
    recorded = {(ref, info["page"]) for ref, info, _ in original.sample(owner, [document], 20)}
    assert {page for _, page in recorded} == {1, 2}
    rebuilt = VectorStore(chromadb.EphemeralClient(), settings)
    rebuilt.name += "-rehearsal"
    with monkeypatch.context() as patch, SessionLocal() as db:
        patch.setattr("app.document_worker.get_vector_store", lambda: rebuilt)
        row = db.get(Document, document)
        ingest(row, settings, now)
        ingest(row, settings, now)
        assert {(ref, info["page"]) for ref, info, _ in rebuilt.sample(owner, [document], 20)} == recorded
        assert rebuilt.sample(other, [document], 20) == []
        db.rollback()
    assert client.delete(f"{ROOT}/{document}", headers=headers).status_code == 202
    run_one(settings)
