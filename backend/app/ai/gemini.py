from google import genai
from google.genai import types

from app.core.config import Settings
from app.services.document_errors import DocumentError


FREE_CHAT_MODELS = {"gemini-3.5-flash-lite"}
FREE_EMBEDDING_MODELS = {"gemini-embedding-2", "gemini-embedding-001"}


def client_for(settings: Settings, *, model: str, allowed: set[str], timeout: int):
    if not settings.gemini_api_key:
        raise DocumentError("Gemini is not configured. Check the backend environment.", retryable=True)
    if not settings.gemini_free_tier_confirmed:
        raise DocumentError("Gemini is disabled until the administrator confirms the API project is on the Free tier.", retryable=True)
    if model.removeprefix("models/") not in allowed:
        raise DocumentError("The configured Gemini model is outside this application's verified Free-tier list.")
    return genai.Client(
        api_key=settings.gemini_api_key.get_secret_value(), vertexai=False,
        http_options=types.HttpOptions(timeout=timeout * 1000, retry_options=types.HttpRetryOptions(attempts=1)),
    )
