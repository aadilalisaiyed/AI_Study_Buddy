from datetime import date, datetime, time
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("Use a valid IANA timezone, such as Asia/Kolkata.") from error


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Preferences(StrictInput):
    timezone: str = Field(default="Asia/Kolkata", max_length=100)
    duration: int = Field(default=45, ge=15, le=180)
    window_start: time = time(17)
    window_end: time = time(21)
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    break_minutes: int = Field(default=10, ge=0, le=120)
    daily_minutes: int = Field(default=120, ge=15, le=720)
    reminder_minutes: int | None = Field(default=15, ge=0, le=1440)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value

    @model_validator(mode="after")
    def validate_window(self):
        if any(value.tzinfo or value.second or value.microsecond for value in (self.window_start, self.window_end)):
            raise ValueError("Study windows use local hours and minutes.")
        if self.window_start >= self.window_end or self.duration > self.daily_minutes:
            raise ValueError("Check the study window, session duration and daily limit.")
        if len(set(self.days)) != len(self.days) or any(day not in range(7) for day in self.days):
            raise ValueError("Study days must be unique weekdays from 0 (Monday) to 6 (Sunday).")
        return self


class PlanInput(StrictInput):
    title: str = Field(min_length=1, max_length=140)
    subject: str = Field(default="", max_length=100)
    topic: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1500)
    local_date: date
    local_time: time
    timezone: str = Field(max_length=100)
    fold: Literal[0, 1] | None = None
    duration: int = Field(ge=15, le=180)
    reminder_minutes: int | None = Field(default=None, ge=0, le=1440)
    source_quiz_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value):
        zone(value)
        return value

    @field_validator("local_time")
    @classmethod
    def valid_time(cls, value):
        if value.tzinfo or value.second or value.microsecond:
            raise ValueError("Enter a local time in hours and minutes.")
        return value


class ProposalInput(StrictInput):
    request_id: UUID
    action: Literal["create", "update", "cancel", "sync"]
    session_id: UUID | None = None
    plan: PlanInput | None = None
    google: bool = False

    @model_validator(mode="after")
    def action_fields(self):
        if (self.action == "create") != (self.session_id is None):
            raise ValueError("Only a new session can omit its session ID.")
        if (self.action in ("create", "update")) != (self.plan is not None):
            raise ValueError("Supply exact session details for create and update only.")
        if self.action == "sync" and not self.google:
            raise ValueError("Select Google Calendar to synchronize.")
        return self


class Confirm(StrictInput):
    approved: Literal[True]

    @field_validator("approved", mode="before")
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True:
            raise ValueError("Confirm the exact reviewed action with approved=true.")
        return value


class CalendarChoice(StrictInput):
    calendar_id: str = Field(min_length=1, max_length=500)


class SessionView(BaseModel):
    id: UUID
    title: str
    subject: str
    topic: str
    description: str
    start_at: datetime
    end_at: datetime
    timezone: str
    reminder_minutes: int | None
    status: str
    version: int
    completed_at: datetime | None
    source_quiz_id: UUID | None
    document_ids: list[UUID]
    sync_status: str
    sync_error: str | None
    calendar_id: str | None
    sync_retry_id: UUID | None = None


class Recommendation(BaseModel):
    topic: str
    subject: str
    priority: int
    reason: str
    activity: str
    duration: int
    accuracy: float
    samples: int
    source_quiz_id: UUID | None
    document_ids: list[UUID]


class Slot(BaseModel):
    start_at: datetime
    end_at: datetime
    local_date: date
    local_time: time
    fold: Literal[0, 1]
    timezone: str


class Availability(BaseModel):
    scope: Literal["local", "google"]
    calendar_name: str | None = None
    slots: list[Slot]


class ProposalView(BaseModel):
    id: UUID
    action: str
    status: str
    session_id: UUID | None
    details: dict
    calendar_name: str | None
    expires_at: datetime
    error: str | None
    session: SessionView | None
