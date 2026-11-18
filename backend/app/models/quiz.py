from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (
        CheckConstraint("status IN ('generating','ready','failed')", name="ck_quiz_status"),
        CheckConstraint("question_count BETWEEN 5 AND 20", name="ck_quiz_count"),
        CheckConstraint("kind IN ('mcq','boolean','short','mixed') AND difficulty IN ('easy','medium','hard','mixed')", name="ck_quiz_configuration"),
        Index("ix_quizzes_owner_created", "user_id", "created_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10))
    difficulty: Mapped[str] = mapped_column(String(10))
    question_count: Mapped[int]
    minutes: Mapped[int | None]
    subject_label: Mapped[str | None] = mapped_column(String(80))
    subject_key: Mapped[str | None] = mapped_column(String(240))
    focus: Mapped[str] = mapped_column(String(160))
    sources: Mapped[list] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(12))
    model: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (
        UniqueConstraint("quiz_id", "position", name="uq_quiz_question_position"),
        CheckConstraint("position >= 1 AND max_marks BETWEEN 1 AND 4", name="ck_quiz_question_marks"),
        CheckConstraint("kind IN ('mcq','boolean','short')", name="ck_quiz_question_kind"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    quiz_id: Mapped[UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    position: Mapped[int]
    kind: Mapped[str] = mapped_column(String(10))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list] = mapped_column(JSONB)
    key: Mapped[dict] = mapped_column(JSONB)
    explanation: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(10))
    topic: Mapped[str] = mapped_column(String(100))
    topic_key: Mapped[str] = mapped_column(String(100))
    max_marks: Mapped[int]
    sources: Mapped[list] = mapped_column(JSONB)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('in_progress','graded')", name="ck_quiz_attempt_status"),
        CheckConstraint("earned_marks >= 0 AND total_marks >= earned_marks", name="ck_quiz_attempt_marks"),
        UniqueConstraint("quiz_id", "request_id", name="uq_quiz_attempt_request"),
        Index("ix_quiz_attempt_owner_submitted", "user_id", "submitted_at", "id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    quiz_id: Mapped[UUID] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(String(12))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_marks: Mapped[int]
    earned_marks: Mapped[int]


class QuizAnswer(Base):
    __tablename__ = "quiz_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_quiz_attempt_question"),
        CheckConstraint("earned_marks >= 0 AND max_marks >= earned_marks", name="ck_quiz_answer_marks"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("quiz_attempts.id", ondelete="CASCADE"))
    question_id: Mapped[UUID] = mapped_column(ForeignKey("quiz_questions.id", ondelete="CASCADE"))
    value: Mapped[dict] = mapped_column(JSONB)
    earned_marks: Mapped[int]
    max_marks: Mapped[int]
    feedback: Mapped[list] = mapped_column(JSONB)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuizUsage(Base):
    __tablename__ = "quiz_generation_usage"
    __table_args__ = (
        UniqueConstraint("user_id", "request_id", name="uq_quiz_generation_request"),
        Index("ix_quiz_usage_owner_created", "user_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    quiz_id: Mapped[UUID | None] = mapped_column(ForeignKey("quizzes.id", ondelete="SET NULL"), index=True)
    request_id: Mapped[UUID]
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12))
    model: Mapped[str | None] = mapped_column(String(80))
    token_usage: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
