from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

from app.ai import embeddings, gemini, llm
from app.core.config import Settings
from app.services.document_errors import DocumentError
from app.services.storage.supabase_storage import SupabaseStorage


def test_private_storage_immutable_and_verifiable():
    objects = {}
    key = "users/owner/documents/document/original.pdf"
    source = b"%PDF-testing"
    digest = sha256(source).hexdigest()

    def handle(request):
        path = request.url.path
        assert request.headers["apikey"] == "test-secret"
        if path.endswith("/bucket/study-documents"):
            return httpx.Response(200, json={"public": False})
        if request.method == "POST":
            assert request.headers["x-upsert"] == "false"
            assert path.endswith(key)
            if key in objects:
                return httpx.Response(409)
            objects[key] = request.read()
            return httpx.Response(200)
        if request.method == "DELETE":
            assert key in request.read().decode()
            objects.pop(key, None)
            return httpx.Response(200, json=[])
        assert "/authenticated/" in path
        return httpx.Response(200, content=objects[key]) if key in objects else httpx.Response(
            400, json={"statusCode": "404"},
        )

    client = httpx.Client(base_url="https://test.supabase.co/storage/v1/", headers={"apikey": "test-secret"},
                          transport=httpx.MockTransport(handle))
    store = SupabaseStorage(client, "study-documents")
    store.ensure_private()
    store.upload(key, BytesIO(source), len(source), digest)
    store.upload(key, BytesIO(source), len(source), digest)
    assert store.download(key, len(source)) == source
    with pytest.raises(DocumentError, match="different bytes"):
        store.upload(key, BytesIO(source), len(source), "b" * 64)
    with pytest.raises(DocumentError, match="exceeds"):
        store.download(key, 1)
    store.delete(key)
    store.delete(key)
    assert not objects


def test_storage_rejects_public_bucket():
    store = SupabaseStorage(httpx.Client(base_url="https://test.supabase.co/", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"public": True}),
    )), "study-documents")
    with pytest.raises(DocumentError, match="private"):
        store.ensure_private()


def test_gemini_free_gate_and_embed_dimensions(monkeypatch):
    requests = []

    def embed(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1] * 768) for _ in kwargs["contents"]])

    monkeypatch.setattr(gemini.genai, "Client", lambda **opts: SimpleNamespace(models=SimpleNamespace(embed_content=embed)))
    with pytest.raises(DocumentError, match="Free tier"):
        embeddings.GeminiEmbeddings(Settings(gemini_api_key="fixture", gemini_free_tier_confirmed=False))
    client = embeddings.GeminiEmbeddings(Settings(gemini_api_key="fixture", gemini_free_tier_confirmed=True))
    assert len(client.embed(["first", "second"])) == 2
    assert requests[0]["contents"][1].parts[0].text.endswith("second")
    client.embed(["find a topic"], query=True)
    assert requests[1]["contents"][0].parts[0].text.startswith("task: search result")
    client.dimension = 256
    with pytest.raises(DocumentError, match="incompatible"):
        client.embed(["first"])


@pytest.mark.parametrize(("status", "expected"), [(429, "provider_quota"), (403, "provider_configuration")])
def test_generation_maps_provider_errors(monkeypatch, status, expected):
    def generate(**kwargs):
        raise errors.ClientError(status, {"error": {"message": "sensitive provider text"}})
    monkeypatch.setattr(gemini.genai, "Client", lambda **opts: SimpleNamespace(
        models=SimpleNamespace(generate_content=generate),
    ))
    client = llm.GeminiTutor(Settings(gemini_api_key="fixture", gemini_free_tier_confirmed=True))
    with pytest.raises(llm.TutorError) as failure:
        client.generate("{}")
    assert failure.value.code == expected
    assert "sensitive" not in str(failure.value)
