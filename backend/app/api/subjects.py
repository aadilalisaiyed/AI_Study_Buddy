from unicodedata import normalize
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.documents import DB, Owner, owned
from app.models.subject import Subject

router = APIRouter(prefix="/api/v1/subjects", tags=["Subjects"])


class Name(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Assignment(BaseModel):
    subject_id: UUID | None


def owned_subject(db, owner, identifier):
    subject = db.scalar(select(Subject).where(Subject.id == identifier, Subject.user_id == owner))
    if subject is None:
        raise HTTPException(404, "Subject not found.")
    return subject


@router.get("")
def list_subjects(owner: Owner, db: DB, offset: int = 0):
    if offset < 0:
        raise HTTPException(422, "Offset must be nonnegative.")
    items = db.scalars(select(Subject).where(Subject.user_id == owner.id)
                      .order_by(Subject.normalized, Subject.id).offset(offset).limit(100))
    return [{"id": item.id, "name": item.name} for item in items]


@router.post("", status_code=201)
def create_subject(data: Name, owner: Owner, db: DB):
    label = " ".join(normalize("NFKC", data.name).split())
    key = label.casefold()
    if not label or len(label) > 80 or len(key) > 240:
        raise HTTPException(422, "Enter a valid subject name.")
    subject = Subject(user_id=owner.id, name=label, normalized=key)
    db.add(subject)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "A subject with that name already exists.") from exc
    return {"id": subject.id, "name": subject.name}


@router.delete("/{subject_id}", status_code=204)
def remove_subject(subject_id: UUID, owner: Owner, db: DB):
    db.delete(owned_subject(db, owner.id, subject_id))
    db.commit()


@router.put("/documents/{document_id}")
def assign(document_id: UUID, data: Assignment, owner: Owner, db: DB):
    document = owned(db, owner.id, document_id, lock=True)
    subject = owned_subject(db, owner.id, data.subject_id) if data.subject_id else None
    document.subject_id = subject.id if subject else None
    db.commit()
    return {"subject_id": document.subject_id}
