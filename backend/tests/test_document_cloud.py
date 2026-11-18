from hashlib import sha256
import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from app.ai.embeddings import get_embeddings
from app.ai.vector_store import get_vector_store, scope
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.main import app
from app.models.document import Document
from app.services.document_errors import DocumentError
from app.services.document_storage import get_storage
from test_document_flow import ROOT, account, run_one, upload
from test_pdf_processor import make_pdf

FACTS = "The four necessary conditions for deadlock are mutual exclusion, hold and wait, no preemption, and circular wait."


def test_live_supabase_gemini_pipeline():
    if os.getenv("RUN_LIVE_DOCUMENT_TEST") != "1" or not os.getenv("DOCUMENT_TEST_DATABASE_URL"):
        pytest.skip("An isolated PostgreSQL URL and explicit live-test opt-in are required.")
    settings = get_settings()
    assert settings.gemini_free_tier_confirmed and settings.gemini_api_key
    assert os.getenv("DOCUMENT_CLOUD_TEST_BUCKET") == settings.supabase_storage_bucket
    store = get_storage()
    store.ensure_private()
    vectors = get_vector_store()
    data = make_pdf("Operating Systems", FACTS)
    with TestClient(app) as client:
        owner, auth = account(client)
        document, _ = upload(client, auth, data, "operating-systems.pdf")
        url = f"{ROOT}/{document}"
        try:
            with SessionLocal() as db:
                item = db.get(Document, document)
                assert item.checksum == sha256(data).hexdigest()
                key = item.storage_key
            public = httpx.get(str(store.client.base_url) + f"object/public/{store.bucket}/{key}", timeout=10)
            assert not public.is_success
            assert store.download(key, len(data)) == data
            assert run_one(settings).document_id == document
            assert client.get(url, headers=auth).json()["status"] == "READY"
            entries = vectors.client.get_collection(vectors.name, embedding_function=None).get(
                where=scope(owner, [document]), include=["metadatas"],
            )
            assert any(meta["page"] == 2 and meta["owner_id"] == str(owner) for meta in entries["metadatas"])
            assert len(get_embeddings().embed(["What is deadlock?"], query=True)[0]) == settings.gemini_embedding_dimensions
            root = "/api/v1/chat/conversations"
            opened = client.post(root, headers=auth, json={"document_ids": [str(document)]})
            answer = client.post(root + "/" + opened.json()["id"] + "/messages", headers=auth, json={
                "request_id": str(uuid4()), "content": "What are the four necessary conditions for deadlock?",
                "document_ids": [str(document)],
            })
            assert answer.status_code == 200
            result = answer.json()[-1]
            assert all(term in result["content"].lower().replace("-", " ") for term in (
                "mutual exclusion", "hold and wait", "no preemption", "circular wait",
            ))
            assert any(citation["page_number"] == 2 for citation in result["citations"])
            assert client.get(url + "/download", headers=auth).content == data
        finally:
            assert client.delete(url, headers=auth).status_code == 202
            assert run_one(settings).document_id == document
            assert client.get(url, headers=auth).status_code == 404
        with pytest.raises(DocumentError) as missing:
            store.download(key, len(data))
        assert missing.value.status == 404
        assert not vectors.client.get_collection(vectors.name, embedding_function=None).get(
            where=scope(owner, [document]), include=[],
        )["ids"]
