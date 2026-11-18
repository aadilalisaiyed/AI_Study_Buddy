from dataclasses import dataclass
import json
import re
from uuid import UUID

from sqlalchemy.orm import Session

from app.ai.llm import TutorError, get_tutor
from app.ai.prompts import TUTOR_PROMPT
from app.ai.retriever import RetrievedChunk, retrieve
from app.core.config import Settings
from app.schemas.chat import Citation
from app.services.document_errors import DocumentError

INSUFFICIENT = "I couldn’t find enough evidence in the selected documents to answer that question. Try narrowing the question or selecting another ready PDF."
MARKER = re.compile(r"\[S\d+\]", re.IGNORECASE)


@dataclass(frozen=True)
class RAGAnswer:
    content: str
    citations: list[Citation]
    model: str | None = None
    usage: dict | None = None


def prepare_context(question: str, history: list[dict], chunks: list[RetrievedChunk], budget: int):
    sources = {}
    passages = []
    payload = {"question": question, "previous_turns": [], "sources": passages}

    def packed():
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def within_budget():
        # A conservative byte budget avoids extra provider calls to count tokens.
        return len(TUTOR_PROMPT.encode()) + len(packed().encode()) <= budget

    if not within_budget():
        raise TutorError("question_too_large", "This question exceeds the tutor's context budget. Shorten it and try again.", 422)
    fingerprints = set()
    for chunk in chunks:
        fingerprint = " ".join(chunk.text.casefold().split())
        if not fingerprint or fingerprint in fingerprints:
            continue
        label = f"S{len(sources) + 1}"
        passages.append({"id": label, "page": chunk.page_number, "text": chunk.text})
        if not within_budget():
            passages.pop()
            continue
        fingerprints.add(fingerprint)
        sources[label] = chunk

    for turn in reversed(history):
        payload["previous_turns"].insert(0, turn)
        if not within_budget():
            payload["previous_turns"].pop(0)
            break
    return packed(), sources


def answer_question(db: Session, *, owner_id: UUID, documents: list[UUID], question: str, history: list[dict], settings: Settings):
    previous = next((turn["text"] for turn in reversed(history) if turn["role"] == "user"), "")
    search = f"Earlier question: {previous[:440]}\nCurrent question: {question}" if previous else question
    try:
        chunks = retrieve(db, owner_id=owner_id, query=search, document_ids=documents, top_k=settings.chat_top_k)
    except DocumentError as error:
        code = "provider_quota" if error.status == 429 else "retrieval_unavailable"
        raise TutorError(code, str(error), error.status) from error
    db.rollback()  # Release the retrieval transaction before calling the model.
    payload, sources = prepare_context(question, history, chunks, settings.chat_context_tokens)
    if not sources:
        return RAGAnswer(INSUFFICIENT, [])

    result = get_tutor().generate(payload)
    if result.answer.insufficient or not result.answer.sections:
        return RAGAnswer(INSUFFICIENT, [], result.model, result.usage)
    by_label = {}
    paragraphs = []
    for section in result.answer.sections:
        if any(label not in sources for label in section.sources):
            return RAGAnswer(INSUFFICIENT, [], result.model, result.usage)
        verified = []
        for label in dict.fromkeys(section.sources):
            chunk = sources[label]
            by_label[label] = Citation(
                source_id=label, document_id=chunk.document_id, filename=chunk.filename,
                page_number=chunk.page_number, chunk_id=chunk.reference, excerpt=chunk.text[:420],
            )
            verified.append(f"[{label}]")
        clean = MARKER.sub("", section.text).strip()
        if not clean:
            return RAGAnswer(INSUFFICIENT, [], result.model, result.usage)
        paragraphs.append(clean + " " + " ".join(verified))
    return RAGAnswer("\n\n".join(paragraphs), list(by_label.values()), result.model, result.usage)
