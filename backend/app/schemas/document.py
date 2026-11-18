from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus


class UploadInit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=512)
    file_size: int = Field(gt=0)
    content_type: str = Field(max_length=80)


class DocumentResponse(BaseModel):
    subject_id: UUID | None = None
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    content_type: str
    file_size: int
    page_count: int
    chunk_count: int
    status: DocumentStatus
    error_message: str | None
    retryable: bool
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class UploadInstructions(BaseModel):
    document: DocumentResponse
    upload_path: str
    complete_path: str


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int
