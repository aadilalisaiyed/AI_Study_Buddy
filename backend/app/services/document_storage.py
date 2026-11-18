from functools import lru_cache
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings
from app.services.document_errors import DocumentError
from app.services.storage.supabase_storage import PDF_MIME, SupabaseStorage

__all__ = ["PDF_MIME", "get_storage"]


@lru_cache
def get_storage() -> SupabaseStorage:
    settings = get_settings()
    key = settings.supabase_secret_key.get_secret_value() if settings.supabase_secret_key else ""
    url = urlsplit(settings.supabase_url)
    if not key or not url.hostname:
        raise DocumentError("Supabase Storage is not configured. Contact the workspace administrator.", retryable=True)
    if (url.scheme != "https" or not url.hostname.endswith(".supabase.co") or url.netloc != url.hostname
            or url.path not in ("", "/") or url.query or url.fragment):
        raise DocumentError("Use the HTTPS project URL from the Supabase dashboard.")
    headers = {"apikey": key}
    if not key.startswith("sb_secret_") and key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    elif not key.startswith("sb_secret_"):
        raise DocumentError("Configure a Supabase server secret key.")
    client = httpx.Client(
        base_url=f"https://{url.hostname}/storage/v1/", headers=headers,
        timeout=httpx.Timeout(25, connect=5), follow_redirects=False,
    )
    return SupabaseStorage(client, settings.supabase_storage_bucket)
