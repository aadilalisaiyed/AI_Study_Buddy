from sqlalchemy import exists, select, text

from app.ai.llm import TutorError
from app.models.conversation import Message
from app.models.quiz import Quiz


def serialize_generation(db):
    db.execute(text("SELECT pg_advisory_xact_lock(7142095033)"))


def require_free_slot(db, current):
    busy = db.scalar(select(
        exists().where(Message.status == "pending", Message.expires_at > current)
        | exists().where(Quiz.status == "generating", Quiz.expires_at > current)
    ))
    if busy:
        raise TutorError("ai_busy", "Gemini is already handling a tutor or quiz request. Try again shortly.", 429)
