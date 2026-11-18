from functools import lru_cache
from math import isfinite
from time import sleep
from typing import Sequence

import httpx
from google.genai import errors, types

from app.ai.gemini import FREE_EMBEDDING_MODELS, client_for
from app.core.config import Settings, get_settings
from app.services.document_errors import DocumentError


class GeminiEmbeddings:
    def __init__(self, settings: Settings):
        self.model = settings.gemini_embedding_model
        self.dimension = settings.gemini_embedding_dimensions
        self.batch_size = settings.embedding_batch_size
        self.retries = settings.gemini_retry_attempts
        self.client = client_for(settings, model=self.model, allowed=FREE_EMBEDDING_MODELS, timeout=16)

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        if not 1 <= len(texts) <= self.batch_size or any(not text.strip() for text in texts):
            raise ValueError("Embedding inputs must be nonempty and within the configured batch size.")

        if self.model.removeprefix("models/") == "gemini-embedding-001":
            contents = list(texts)
            config = types.EmbedContentConfig(
                output_dimensionality=self.dimension, task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
            )
        else:
            contents = [types.Content(parts=[types.Part.from_text(
                text=f"task: search result | query: {text}" if query else f"title: none | text: {text}",
            )]) for text in texts]
            config = types.EmbedContentConfig(output_dimensionality=self.dimension)

        for attempt in range(self.retries):
            try:
                response = self.client.models.embed_content(model=self.model, contents=contents, config=config)
                values = [list(item.values or []) for item in response.embeddings or []]
                if len(values) != len(texts) or any(
                    len(row) != self.dimension or not all(isfinite(value) for value in row) for row in values
                ):
                    raise DocumentError("Gemini returned incompatible embeddings. Check the configured model and dimensions.")
                return values
            except (errors.APIError, httpx.TransportError) as error:
                code = getattr(error, "code", 503)
                if code == 429:
                    raise DocumentError("Gemini's Free-tier embedding quota is exhausted. Retry later.", 429, retryable=True) from error
                transient = code in (408, 500, 502, 503, 504)
                if not transient or attempt + 1 == self.retries:
                    message = (
                        "Gemini embeddings are temporarily unavailable. Retry processing later." if transient
                        else "Gemini rejected the embeddings request. Check the server model, limits, and credentials."
                    )
                    raise DocumentError(message, retryable=transient) from error
                sleep(2 ** attempt)
        raise AssertionError("Embedding retry loop exited unexpectedly.")


@lru_cache
def get_embeddings() -> GeminiEmbeddings:
    return GeminiEmbeddings(get_settings())
