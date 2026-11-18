
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str

    jwt_secret_key: str
    jwt_algorithm: Literal["HS256"] = "HS256"
    production: bool = False
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    trusted_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    access_token_expire_minutes: int = 30


    storage_provider: Literal["supabase"] = "supabase"
    supabase_url: str = ""
    supabase_secret_key: SecretStr | None = None
    supabase_storage_bucket: str = "study-documents"
    max_documents_per_user: int = Field(default=20, ge=1, le=100)
    total_document_storage_mb: int = Field(default=750, ge=1, le=900)
    max_pdf_size_mb: int = Field(default=25, ge=1, le=25)
    max_pdf_pages: int = Field(default=250, ge=1, le=1000)
    max_pdf_text_chars: int = Field(default=500_000, ge=1000, le=2_000_000)
    max_pdf_chunks: int = Field(default=600, ge=1, le=3000)
    pdf_chunk_size: int = Field(default=1000, ge=100, le=2000)
    pdf_chunk_overlap: int = Field(default=150, ge=0)

    gemini_api_key: SecretStr | None = None
    gemini_free_tier_confirmed: bool = False
    gemini_chat_model: str = "gemini-3.5-flash-lite"
    gemini_chat_temperature: float = Field(default=0.2, ge=0, le=1)
    gemini_chat_max_output_tokens: int = Field(default=1024, ge=256, le=2048)
    gemini_chat_timeout_seconds: int = Field(default=20, ge=5, le=30)
    gemini_retry_attempts: int = Field(default=2, ge=1, le=3)
    google_oauth_client_id: str = ""
    google_oauth_client_secret: SecretStr | None = None
    google_oauth_redirect_uri: str = "http://127.0.0.1:8000/api/v1/integrations/google/callback"
    google_calendar_scopes: str = (
        "https://www.googleapis.com/auth/calendar.events "
        "https://www.googleapis.com/auth/calendar.calendarlist.readonly openid email"
    )
    google_calendar_timezone: str = "Asia/Kolkata"
    calendar_token_encryption_key: SecretStr | None = None
    planner_frontend_url: str = "http://127.0.0.1:5173"
    calendar_requests_per_minute: int = Field(default=15, ge=1, le=30)
    quiz_max_questions: Literal[5, 10, 15, 20] = 20
    quiz_max_documents: int = Field(default=5, ge=1, le=10)
    quiz_daily_generations: int = Field(default=3, ge=1, le=10)
    quiz_context_chars: int = Field(default=11000, ge=2500, le=18000)
    quiz_max_output_tokens: int = Field(default=8192, ge=2500, le=12000)
    quiz_weak_min_answers: int = Field(default=3, ge=2, le=30)
    quiz_weak_threshold: int = Field(default=65, ge=1, le=99)
    chat_top_k: int = Field(default=6, ge=1, le=12)
    chat_context_tokens: int = Field(default=5000, ge=1500, le=9000)
    chat_history_messages: int = Field(default=8, ge=0, le=16)
    chat_max_documents: int = Field(default=5, ge=1, le=10)
    chat_requests_per_minute: int = Field(default=3, ge=1, le=15)
    chat_requests_per_day: int = Field(default=20, ge=1, le=100)
    chat_max_concurrent: int = Field(default=1, ge=1, le=2)
    gemini_embedding_model: str = "gemini-embedding-2"
    gemini_embedding_dimensions: int = Field(default=768, ge=128, le=3072)
    embedding_batch_size: int = Field(default=16, ge=1, le=32)
    chroma_host: str = "127.0.0.1"
    chroma_port: int = Field(default=8001, ge=1, le=65535)
    chroma_ssl: bool = False

    upload_expiry_hours: int = Field(default=24, ge=1, le=168)
    document_max_attempts: int = Field(default=4, ge=1, le=8)
    document_poll_seconds: float = Field(default=2, gt=0, le=60)
    document_job_timeout_seconds: int = Field(default=600, ge=10, le=3600)

    @model_validator(mode="after")
    def validate_document_settings(self):
        if "*" in self.trusted_hosts or any("*" in origin for origin in self.cors_origins):
            raise ValueError("Use explicit frontend origins and trusted hosts")
        if self.production and (len(self.jwt_secret_key) < 32
                                or not self.cors_origins
                                or any(not origin.startswith("https://") for origin in self.cors_origins)
                                or self.trusted_hosts == ["localhost", "127.0.0.1", "testserver"]):
            raise ValueError("Production needs a strong JWT secret, explicit hosts, and HTTPS origins")
        if self.pdf_chunk_overlap >= self.pdf_chunk_size:
            raise ValueError("PDF_CHUNK_OVERLAP must be smaller than PDF_CHUNK_SIZE")
        if self.chat_requests_per_minute > self.chat_requests_per_day:
            raise ValueError("CHAT_REQUESTS_PER_MINUTE cannot exceed CHAT_REQUESTS_PER_DAY")
        return self

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
