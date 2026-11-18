from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ConversationCreate(ChatInput):
    title: str = Field(default="New conversation", min_length=1, max_length=120)
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)


class ConversationUpdate(ChatInput):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    document_ids: list[UUID] | None = Field(default=None, max_length=10)


class Question(ChatInput):
    request_id: UUID
    content: str = Field(min_length=1, max_length=1200)
    document_ids: list[UUID] = Field(min_length=1, max_length=10)


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class ConversationDetail(ConversationView):
    document_ids: list[UUID]


class ConversationList(BaseModel):
    items: list[ConversationView]
    has_more: bool
    max_documents: int


class Citation(BaseModel):
    source_id: str
    document_id: UUID
    filename: str
    page_number: int = Field(ge=1)
    chunk_id: str | None
    excerpt: str | None
    available: bool = True


class MessageView(BaseModel):
    id: UUID
    request_id: UUID
    ordinal: int
    role: Literal["user", "assistant"]
    status: Literal["pending", "completed", "failed"]
    content: str
    created_at: datetime
    citations: list[Citation]
    error_code: str | None


class MessageList(BaseModel):
    items: list[MessageView]
    next_before: int | None
