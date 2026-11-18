from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

Kind = Literal["mcq", "boolean", "short"]
Difficulty = Literal["easy", "medium", "hard"]
QuizKind = Literal["mcq", "boolean", "short", "mixed"]
QuizDifficulty = Literal["easy", "medium", "hard", "mixed"]
Value = StrictInt | StrictBool | StrictStr | None
UtcDatetime = Annotated[datetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Generate(Input):
    request_id: UUID
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)
    kind: QuizKind = "mcq"
    difficulty: QuizDifficulty = "medium"
    question_count: Literal[5, 10, 15, 20] = 5
    minutes: int | None = Field(default=None, ge=1, le=90)
    focus: str = Field(default="", max_length=160)
    weak_practice: bool = False
    subject_id: UUID | None = None


class Start(Input):
    request_id: UUID


class Save(Input):
    answers: dict[UUID, Value] = Field(max_length=20)


class Source(BaseModel):
    document_id: UUID
    filename: str


class Citation(Source):
    source_id: str
    page_number: int
    chunk_id: str | None
    available: bool


class QuizView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    kind: QuizKind
    difficulty: QuizDifficulty
    question_count: int
    minutes: int | None
    focus: str
    sources: list[Source]
    status: str
    error_message: str | None
    created_at: UtcDatetime


class QuestionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    position: int
    kind: Kind
    prompt: str
    options: list[str]
    max_marks: int


class AttemptView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    quiz_id: UUID
    status: str
    started_at: UtcDatetime
    deadline: UtcDatetime | None
    submitted_at: UtcDatetime | None


class AttemptDetail(AttemptView):
    quiz: QuizView
    questions: list[QuestionView]
    answers: dict[UUID, Value]


class Breakdown(BaseModel):
    label: str
    questions: int
    earned: int
    total: int
    percentage: float


class Review(QuestionView):
    answer: Value
    correct_answer: Value
    explanation: str
    topic: str
    difficulty: Difficulty
    earned: int
    feedback: list[str]
    citations: list[Citation]


class Result(BaseModel):
    attempt: AttemptView
    quiz: QuizView
    earned: int
    total: int
    percentage: float
    correct: int
    incorrect: int
    partial: int
    unanswered: int
    duration_seconds: int
    topics: list[Breakdown]
    difficulties: list[Breakdown]
    questions: list[Review]
