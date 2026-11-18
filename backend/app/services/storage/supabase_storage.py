from hashlib import sha256
from typing import BinaryIO
from urllib.parse import quote

import httpx

from app.services.document_errors import DocumentError

PDF_MIME = "application/pdf"


class SupabaseStorage:
    def __init__(self, client: httpx.Client, bucket: str):
        self.client = client
        self.bucket = quote(bucket, safe="")

    def ensure_private(self) -> None:
        response = self._request("GET", f"bucket/{self.bucket}")
        self._check(response)
        try:
            if response.json().get("public") is False:
                return
        except (ValueError, AttributeError):
            pass
        raise DocumentError("Configure the Supabase document bucket as private before using it.")

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self.client.request(method, path, **kwargs)
        except httpx.TransportError as error:
            raise DocumentError("Supabase Storage is temporarily unavailable.", retryable=True) from error

    @staticmethod
    def _check(response: httpx.Response) -> None:
        code = response.status_code
        if response.is_success:
            return
        if code in (401, 403):
            raise DocumentError("Supabase Storage authorization failed. Check the server key and bucket.")
        if code in (402, 413, 429, 507):
            raise DocumentError("Supabase Storage has reached a size, rate, or usage limit.", 413 if code == 413 else 429)
        raise DocumentError("Supabase Storage could not complete the operation.", retryable=code >= 500 or code == 408)

    def _path(self, key: str, *, authenticated: bool = False) -> str:
        segment = "authenticated/" if authenticated else ""
        return f"object/{segment}{self.bucket}/{quote(key, safe='/')}"

    def upload(self, key: str, source: BinaryIO, size: int, checksum: str) -> None:
        source.seek(0)
        response = self._request("POST", self._path(key), content=iter(lambda: source.read(65536), b""), headers={
            "Content-Type": PDF_MIME, "Content-Length": str(size), "x-upsert": "false",
            "Cache-Control": "private, no-store",
        })
        if response.status_code in (400, 409):
            try:
                existing = self.download(key, size)
            except DocumentError as error:
                if error.status != 404:
                    raise
                self._check(response)
            else:
                if len(existing) != size or sha256(existing).hexdigest() != checksum:
                    raise DocumentError("This upload already contains different bytes. Start a new upload.", 409)
                return
        self._check(response)

    def download(self, key: str, size: int) -> bytes:
        try:
            with self.client.stream("GET", self._path(key, authenticated=True)) as response:
                if response.status_code in (400, 404):
                    if response.status_code == 404:
                        raise DocumentError("The original PDF is unavailable.", 404)
                    # Some Storage gateway versions wrap NoSuchKey in HTTP 400.
                    response.read()
                    try:
                        missing = response.json().get("statusCode") in ("404", 404)
                    except (ValueError, AttributeError):
                        missing = False
                    if missing:
                        raise DocumentError("The original PDF is unavailable.", 404)
                self._check(response)
                data = bytearray()
                for block in response.iter_bytes(chunk_size=65536):
                    if len(data) + len(block) > size:
                        raise DocumentError("The stored PDF exceeds its recorded size.", 422)
                    data.extend(block)
                return bytes(data)
        except httpx.TransportError as error:
            raise DocumentError("Supabase Storage is temporarily unavailable.", retryable=True) from error

    def delete(self, key: str) -> None:
        response = self._request("DELETE", f"object/{self.bucket}", json={"prefixes": [key]})
        self._check(response)
        try:
            self.download(key, 0)
        except DocumentError as error:
            if error.status == 404:
                return
            raise DocumentError("Supabase Storage could not verify deletion.", retryable=True) from error
        raise DocumentError("Supabase Storage could not confirm deletion.", retryable=True)
