from functools import lru_cache
from hashlib import sha256
from typing import Sequence
from uuid import UUID

import chromadb
from chromadb.errors import NotFoundError

from app.core.config import Settings, get_settings
from app.services.document_errors import DocumentError
from app.services.pdf_processor import PIPELINE_VERSION, Chunk


def collection_name(settings: Settings) -> str:
    pipeline = (
        f"{PIPELINE_VERSION}:{settings.gemini_embedding_model}:{settings.gemini_embedding_dimensions}:"
        f"{settings.pdf_chunk_size}:{settings.pdf_chunk_overlap}"
    )
    return "study-docs-" + sha256(pipeline.encode()).hexdigest()[:24]


def scope(owner: UUID, documents: Sequence[UUID]) -> dict:
    if not documents:
        raise ValueError("A document scope is required.")
    return {"$and": [{"owner_id": str(owner)}, {"document_id": {"$in": [str(item) for item in documents]}}]}


class VectorStore:
    def __init__(self, client, settings: Settings):
        self.client = client
        self.settings = settings
        self.name = collection_name(settings)

    def _collection(self):
        return self.client.get_or_create_collection(
            name=self.name, embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={
                "embedding_model": self.settings.gemini_embedding_model,
                "dimensions": self.settings.gemini_embedding_dimensions,
                "pipeline": PIPELINE_VERSION,
            },
        )

    def upsert(self, owner: UUID, document: UUID, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        try:
            self._collection().upsert(
                ids=[chunk.id for chunk in chunks],
                embeddings=vectors,
                documents=[chunk.text for chunk in chunks],
                metadatas=[{
                    "owner_id": str(owner), "document_id": str(document), "chunk_id": chunk.id,
                    "page": chunk.page, "chunk_index": chunk.index, "checksum": chunk.checksum,
                    "pipeline": PIPELINE_VERSION, "embedding_model": self.settings.gemini_embedding_model,
                } for chunk in chunks],
            )
        except Exception as error:
            raise DocumentError("The document index could not store this batch. Retry processing.", retryable=True) from error

    def verify(self, owner: UUID, document: UUID, chunks: list[Chunk]) -> None:
        predicate = scope(owner, [document])
        expected = {chunk.id for chunk in chunks}
        try:
            collection = self._collection()
            found = collection.get(where=predicate, include=[], limit=len(chunks) + 1)
        except Exception as error:
            raise DocumentError("The document index could not be verified. Retry processing.", retryable=True) from error
        if set(found["ids"]) != expected:
            raise DocumentError("The document index is incomplete. Retry processing.", retryable=True)

    def delete(self, name: str, owner: UUID, document: UUID) -> None:
        try:
            collection = self.client.get_collection(name=name, embedding_function=None)
            predicate = scope(owner, [document])
            collection.delete(where=predicate)
            if collection.get(where=predicate, limit=1, include=[])["ids"]:
                raise DocumentError("The document index could not confirm deletion.", retryable=True)
        except NotFoundError:
            return
        except Exception as error:
            raise DocumentError("The document index could not confirm deletion.", retryable=True) from error

    def sample(self, owner: UUID, documents: Sequence[UUID], limit: int):
        """Sample in page order with round-robin representation across PDFs."""
        try:
            collection = self.client.get_collection(name=self.name, embedding_function=None)
            groups = []
            for document in documents:
                result = collection.get(where=scope(owner, [document]), include=["metadatas"], limit=limit)
                ordered = sorted(zip(result["ids"], result["metadatas"], strict=True),
                                 key=lambda item: (item[1]["page"], item[1]["chunk_index"]))
                count = min(8, len(ordered))
                if count:
                    positions = [round(i * (len(ordered) - 1) / max(1, count - 1)) for i in range(count)]
                    groups.append([ordered[position][0] for position in positions])
            ids = [group[i] for i in range(8) for group in groups if i < len(group)]
            if not ids:
                return []
            rows = collection.get(ids=ids, where=scope(owner, documents), include=["metadatas", "documents"])
            by_id = {ref: (ref, metadata, passage) for ref, metadata, passage in zip(
                rows["ids"], rows["metadatas"], rows["documents"], strict=True,
            )}
            return [by_id[ref] for ref in ids if ref in by_id]
        except NotFoundError:
            return []
        except Exception as error:
            raise DocumentError("The study index could not sample these PDFs.", retryable=True) from error

    def query(self, owner: UUID, documents: Sequence[UUID], vector: list[float], top_k: int):
        predicate = scope(owner, documents)
        try:
            collection = self.client.get_collection(name=self.name, embedding_function=None)
            return collection.query(
                query_embeddings=[vector], n_results=top_k,
                where=predicate, include=["documents", "metadatas", "distances"],
            )
        except NotFoundError:
            return None
        except Exception as error:
            raise DocumentError("The document index is temporarily unavailable.", retryable=True) from error


@lru_cache
def get_vector_store() -> VectorStore:
    settings = get_settings()
    try:
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port, ssl=settings.chroma_ssl)
    except Exception as error:
        raise DocumentError("The document index is temporarily unavailable.", retryable=True) from error
    return VectorStore(client, settings)
