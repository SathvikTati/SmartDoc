"""Persisted query history.

Every answered question is stored with its full result, so history survives
a browser refresh and a question asked last week can still be reopened with
the citations and retrieval trace it originally produced.

Recording is best-effort. A history table that cannot be written must never
turn a successful answer into an error — the user asked a question and got
one; failing the request over bookkeeping would be the wrong trade.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from port6.services.db.database import SessionLocal
from port6.services.model.models import Chat, QueryRun
from port6.services.rag.base import RagResult
from port6.services.settings.defaults import PROMPT_DEFAULTS
from port6.services.settings.service import get_int, prompt_version


logger = logging.getLogger(__name__)


# Which prompts each mode actually invokes, so a run records only the
# versions that could have influenced its answer.
PROMPTS_BY_MODE = {
    "naive": ["answer_generation"],
    "hybrid": ["answer_generation"],
    "agentic": [
        "retrieval_planner",
        "evidence_validation",
        "answer_generation",
    ],
}


def _prompt_versions(mode: str) -> dict:

    names = PROMPTS_BY_MODE.get(mode, list(PROMPT_DEFAULTS))

    return {name: prompt_version(name) for name in names}


def record_run(
    question: str,
    mode: str,
    top_k: int,
    result: RagResult,
    chat_id: str | None = None,
    turn_index: int = 0,
    resolution: dict | None = None,
) -> str | None:
    """Store one answered question. Returns the run id, or None on failure."""

    resolution = resolution or {}

    db = SessionLocal()

    try:
        run = QueryRun(
            chat_id=chat_id,
            turn_index=turn_index,
            relation=resolution.get("relation"),
            standalone_question=resolution.get("standalone_question"),
            context_strategy=resolution.get("strategy"),
            question=question,
            mode=mode,
            top_k=top_k,
            answer=result.answer,
            answered=result.answered,
            citation_count=len(result.citations),
            chunk_count=len(result.retrieved_chunks),
            latency_ms=result.latency_ms,
            retrieval_method=result.retrieval_method,
            # mode="json" so UUIDs and enums land as JSON-safe values.
            result=result.model_dump(mode="json"),
            prompt_versions=_prompt_versions(mode),
        )

        db.add(run)
        db.commit()
        db.refresh(run)

        _trim(db)

        return str(run.id)

    except Exception as exc:
        db.rollback()
        logger.warning("Could not record query history: %s", exc)
        return None

    finally:
        db.close()


def _trim(db: Session) -> None:
    """Keep history bounded, oldest first."""

    keep = get_int("history.retain_runs")

    total = db.query(QueryRun.id).count()

    if total <= keep:
        return

    stale = (
        db.query(QueryRun.id)
        .order_by(QueryRun.created_at.asc())
        .limit(total - keep)
        .all()
    )

    db.query(QueryRun).filter(
        QueryRun.id.in_([row.id for row in stale])
    ).delete(synchronize_session=False)

    db.commit()

    logger.info("Trimmed %d query runs beyond the retention limit", len(stale))


def list_runs(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    mode: str | None = None,
    answered: bool | None = None,
) -> dict:
    """Newest first. Returns summaries only — not the full stored result."""

    query = db.query(QueryRun)

    if mode:
        query = query.filter(QueryRun.mode == mode)

    if answered is not None:
        query = query.filter(QueryRun.answered == answered)

    total = query.count()

    runs = (
        query.order_by(QueryRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {"total": total, "runs": runs}


def get_run(
    db: Session,
    run_id: UUID,
) -> QueryRun:

    run = db.query(QueryRun).filter(QueryRun.id == run_id).first()

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Query run not found",
        )

    return run


def delete_run(
    db: Session,
    run_id: UUID,
) -> None:

    run = get_run(db, run_id)
    chat_id = run.chat_id

    db.delete(run)
    db.commit()

    # A conversation with no turns left is not a conversation. Without
    # this the sidebar kept listing chats whose questions had all been
    # deleted — the cascade only runs chat -> runs, never the reverse.
    if chat_id is not None:
        prune_empty_chats(db, chat_id)


def clear_runs(db: Session) -> int:
    """Delete every question, and the conversations they belonged to."""

    removed = db.query(QueryRun).delete()

    # Same reason: clearing history has to clear the chats too, or the
    # UI keeps showing conversations that contain nothing.
    db.query(Chat).delete()

    db.commit()

    return removed


def prune_empty_chats(
    db: Session,
    chat_id: UUID | None = None,
) -> int:
    """Remove conversations that have no turns left.

    Scoped to one chat after a delete; unscoped as a sweep for rows left
    behind before this was handled.
    """

    query = db.query(Chat).filter(
        ~db.query(QueryRun)
        .filter(QueryRun.chat_id == Chat.id)
        .exists()
    )

    if chat_id is not None:
        query = query.filter(Chat.id == chat_id)

    empty = query.all()

    for chat in empty:
        db.delete(chat)

    if empty:
        db.commit()
        logger.info("Removed %d conversation(s) with no turns", len(empty))

    return len(empty)
