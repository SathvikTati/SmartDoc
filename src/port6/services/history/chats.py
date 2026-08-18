"""Conversations: the turns a follow-up is resolved against."""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from port6.services.db.database import SessionLocal
from port6.services.model.models import Chat, QueryRun
from port6.services.rag.base import RetrievedChunk


logger = logging.getLogger(__name__)


TITLE_CHARACTERS = 80


def title_from(question: str) -> str:
    """A chat is named after the question that started it."""

    cleaned = " ".join((question or "").split()) or "Untitled"

    if len(cleaned) <= TITLE_CHARACTERS:
        return cleaned

    return cleaned[:TITLE_CHARACTERS].rstrip() + "…"


def get_chat(
    db: Session,
    chat_id: UUID,
) -> Chat:

    chat = db.query(Chat).filter(Chat.id == chat_id).first()

    if chat is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found",
        )

    return chat


def ensure_chat(
    chat_id: UUID | None,
    question: str,
) -> tuple[str, int]:
    """Find or start a chat. Returns its id and the next turn index.

    Every question belongs to a conversation, even a one-off — the caller
    gets an id back and can continue from it without having decided up
    front that it wanted a chat.
    """

    db = SessionLocal()

    try:
        if chat_id is not None:
            chat = db.query(Chat).filter(Chat.id == chat_id).first()

            if chat is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Chat not found",
                )

            turn = (
                db.query(QueryRun)
                .filter(QueryRun.chat_id == chat.id)
                .count()
            )

            chat.updated_at = datetime.utcnow()
            db.commit()

            return str(chat.id), turn

        chat = Chat(title=title_from(question))

        db.add(chat)
        db.commit()
        db.refresh(chat)

        return str(chat.id), 0

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def load_turns(
    chat_id: str,
    limit: int,
) -> list[dict]:
    """Recent turns, oldest-first, in the shape the classifier expects.

    Only what resolution needs — the question, the answer and which
    documents were used. The stored result is much larger and none of the
    rest helps decide whether a question is a follow-up.
    """

    db = SessionLocal()

    try:
        runs = (
            db.query(QueryRun)
            .filter(QueryRun.chat_id == chat_id)
            .order_by(QueryRun.turn_index.desc())
            .limit(limit)
            .all()
        )

    except Exception as exc:
        logger.warning("Could not load conversation turns: %s", exc)
        return []

    finally:
        db.close()

    turns = []

    for run in reversed(runs):

        result = run.result or {}

        documents = sorted(
            {
                chunk.get("filename")
                for chunk in result.get("retrieved_chunks") or []
                if chunk.get("filename")
            }
        )

        turns.append(
            {
                "question": run.question,
                "answer": run.answer,
                "documents": documents,
                "turn_index": run.turn_index,
            }
        )

    return turns


def previous_chunks(chat_id: str) -> list[RetrievedChunk]:
    """The chunks the last turn retrieved, rebuilt from its stored result."""

    db = SessionLocal()

    try:
        run = (
            db.query(QueryRun)
            .filter(QueryRun.chat_id == chat_id)
            .order_by(QueryRun.turn_index.desc())
            .first()
        )

    except Exception as exc:
        logger.warning("Could not load previous chunks: %s", exc)
        return []

    finally:
        db.close()

    if run is None:
        return []

    chunks = []

    for raw in (run.result or {}).get("retrieved_chunks") or []:
        try:
            chunks.append(RetrievedChunk(**raw))

        except Exception:
            # A stored result from an older shape should not break the
            # current turn; skip what cannot be rebuilt.
            continue

    return chunks


# -------------------------------------------------------------------
# Read API
# -------------------------------------------------------------------

def list_chats(
    db: Session,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Most recently active first."""

    # Defensive: a chat with no turns is not worth showing even if one
    # survives a delete path that failed to clean up.
    query = db.query(Chat).filter(
        db.query(QueryRun).filter(QueryRun.chat_id == Chat.id).exists()
    )

    total = query.count()

    chats = (
        query.order_by(Chat.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    counts = {}

    if chats:
        for chat in chats:
            counts[chat.id] = (
                db.query(QueryRun)
                .filter(QueryRun.chat_id == chat.id)
                .count()
            )

    return {
        "total": total,
        "chats": [
            {
                "id": chat.id,
                "title": chat.title,
                "turn_count": counts.get(chat.id, 0),
                "created_at": chat.created_at,
                "updated_at": chat.updated_at,
            }
            for chat in chats
        ],
    }


def chat_turns(
    db: Session,
    chat_id: UUID,
) -> dict:
    """A chat with every turn in order, each carrying its full result."""

    chat = get_chat(db, chat_id)

    runs = (
        db.query(QueryRun)
        .filter(QueryRun.chat_id == chat.id)
        .order_by(QueryRun.turn_index.asc())
        .all()
    )

    return {
        "id": chat.id,
        "title": chat.title,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
        "turns": runs,
    }


def delete_chat(
    db: Session,
    chat_id: UUID,
) -> None:

    chat = get_chat(db, chat_id)

    # query_runs.chat_id cascades, so the turns go with it.
    db.delete(chat)
    db.commit()
