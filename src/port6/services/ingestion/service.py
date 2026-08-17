"""Document ingestion pipeline.

Runs after upload: chunk, embed, summarise, then mark the document ready.

These functions are synchronous on purpose. FastAPI runs sync background
tasks in a worker thread, so a long ingestion never blocks the event loop
that is serving requests.

A document is identified by its filename. Nothing here tries to infer a
title, a type or an owning department from the content — that cost a model
call per upload to produce a label no part of the system could verify.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from langchain_core.documents import Document as LangChainDocument

from port6.services.chunking.service import chunk_document
from port6.services.db.database import SessionLocal
from port6.services.llm.errors import describe as describe_failure
from port6.services.llm.service import get_chat_model
from port6.services.model.models import Document
from port6.services.parsers.parser import ParsedBlock, parse
from port6.services.settings.service import get_int, get_prompt
from port6.services.vector.chroma import (
    delete_document_chunks,
    store_chunks,
)


logger = logging.getLogger(__name__)


STATUS_PROCESSING = "PROCESSING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"


def _load_document(
    db,
    document_id: str,
) -> Document:

    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if document is None:
        raise ValueError(
            f"Document {document_id} not found"
        )

    return document


def set_status(
    document_id: str,
    status: str,
    error_message: str | None = None,
) -> None:

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)

        document.status = status

        if error_message is not None:
            document.error_message = error_message

        db.commit()

        logger.info(
            "Document %s marked as %s",
            document_id,
            status,
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def mark_failed(
    document_id: str,
    error: Exception,
) -> dict:
    """Park a failed document with enough detail to act on it.

    Nothing is deleted: the uploaded file is still on disk, so a document
    that failed because Ollama was down or a key had expired can be
    reprocessed once that is fixed. The classified `failure_kind` is what
    tells the UI whether retrying is worth offering.
    """

    failure = describe_failure(error)

    db = SessionLocal()

    try:
        document = (
            db.query(Document)
            .filter(Document.id == document_id)
            .first()
        )

        if document is None:
            logger.warning(
                "Cannot mark missing document %s as FAILED",
                document_id,
            )
            return failure

        document.status = STATUS_FAILED
        document.error_message = failure["message"]
        document.failure_kind = failure["kind"]

        db.commit()

        logger.error(
            "Document %s marked as FAILED (%s/%s): %s",
            document_id,
            failure["kind"],
            failure["reason"],
            failure["message"],
        )

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    return failure


def record_attempt(
    document_id: str,
) -> int:
    """Count a processing attempt and clear the previous failure."""

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)

        document.attempts = (document.attempts or 0) + 1
        document.last_attempt_at = datetime.utcnow()
        document.error_message = None
        document.failure_kind = None

        db.commit()

        return document.attempts

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def load_blocks(
    document: Document,
) -> list[ParsedBlock]:
    """Re-parse the stored file to recover headings and page numbers.

    Only the plain text is kept in the database, so the structure has to come
    from the file. If it is gone, ingestion still works — the document is
    simply treated as one unstructured section.
    """

    storage_path = Path(document.storage_path)

    if not storage_path.exists():
        logger.warning(
            "Stored file missing for %s; chunking without structure",
            document.id,
        )
        return []

    try:
        return parse(storage_path).blocks

    except Exception as exc:
        logger.warning(
            "Could not re-parse %s for structure (%s); "
            "chunking without it",
            document.filename,
            exc,
        )
        return []


def build_chunks(
    document_id: str,
) -> list[LangChainDocument]:

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)

        chunks = chunk_document(
            document_id=str(document.id),
            filename=document.filename,
            content=document.content,
            blocks=load_blocks(document),
        )

        logger.info(
            "Document %s split into %d chunks",
            document_id,
            len(chunks),
        )

        return chunks

    finally:
        db.close()


def embed_chunks(
    document_id: str,
    chunks: list[LangChainDocument],
) -> int:

    if not chunks:
        raise ValueError(
            f"Document {document_id} produced no chunks"
        )

    # Re-ingesting a document can produce fewer chunks than last time, so
    # clear the old ones rather than leaving orphans behind at higher indices.
    delete_document_chunks(document_id)

    stored_count = store_chunks(chunks)

    logger.info(
        "Stored %d chunks in the vector store for document %s",
        stored_count,
        document_id,
    )

    return stored_count


def _run_summary_prompt(
    prompt_name: str,
    filename: str,
    content: str,
    max_words: int,
) -> str:

    chain = get_prompt(prompt_name) | get_chat_model()

    response = chain.invoke(
        {
            "filename": filename,
            "content": content,
            "max_words": max_words,
        }
    )

    text = response.content

    if not isinstance(text, str):
        text = str(text)

    return text.strip()


def split_for_summary(
    content: str,
    window: int,
    max_parts: int,
) -> list[str]:
    """Cut a document into at most `max_parts` windows covering all of it.

    A document longer than `window * max_parts` is sampled evenly across
    its whole length rather than truncated to the opening: the point of
    the summary is to describe the document, and stage 1 ranks on it.
    """

    if len(content) <= window:
        return [content]

    parts_needed = -(-len(content) // window)

    if parts_needed <= max_parts:
        return [
            content[start : start + window]
            for start in range(0, len(content), window)
        ]

    # Too long to read whole: take `max_parts` evenly spaced windows so the
    # sample spans the document instead of clustering at the start.
    stride = (len(content) - window) // (max_parts - 1)

    return [
        content[index * stride : index * stride + window]
        for index in range(max_parts)
    ]


def summarize_document(
    document_id: str,
) -> str:
    """Summarise a document, in one call or several.

    The summary is not decoration: stage 1 of hierarchical retrieval ranks
    documents on it, so summarising only a long document's opening made
    the largest files the hardest to find.
    """

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)
        filename = document.filename
        content = (document.content or "").strip()

    finally:
        db.close()

    if not content:
        raise ValueError(
            f"Document {document_id} has no content to summarise"
        )

    window = get_int("summary.max_input_characters")
    max_words = get_int("summary.max_words")
    max_parts = max(get_int("summary.max_sections"), 1)

    parts = split_for_summary(content, window, max_parts)

    if len(parts) == 1:
        summary = _run_summary_prompt(
            "document_summary",
            filename,
            parts[0],
            max_words,
        )

    else:
        logger.info(
            "Document %s is %d characters; summarising in %d parts",
            document_id,
            len(content),
            len(parts),
        )

        # Each part gets a share of the budget, then the whole is written
        # to the full length.
        part_words = max(max_words // len(parts), 40)

        part_summaries = [
            _run_summary_prompt(
                "document_summary",
                filename,
                part,
                part_words,
            )
            for part in parts
        ]

        summary = _run_summary_prompt(
            "document_summary_combine",
            filename,
            "\n\n".join(
                f"Part {index}: {text}"
                for index, text in enumerate(part_summaries, start=1)
            ),
            max_words,
        )

    db = SessionLocal()

    try:
        stored = _load_document(db, document_id)
        stored.summary = summary
        db.commit()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()

    logger.info(
        "Summarised document %s from %d characters in %d call(s)",
        document_id,
        len(content),
        len(parts) + (1 if len(parts) > 1 else 0),
    )

    return summary


def _record_summary_failure(
    document_id: str,
    failure: dict,
) -> None:
    """Note a missing summary on an otherwise-ready document."""

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)

        document.error_message = (
            f"Indexed, but not summarised: {failure['message']} "
            "This document can still be found by chunk, but not ranked "
            "at the document level. Reprocess to fill the summary in."
        )
        document.failure_kind = failure["kind"]

        db.commit()

    except Exception:
        db.rollback()

    finally:
        db.close()


def process_document(
    document_id: str,
) -> None:
    """Take one uploaded document all the way to READY.

    Any failure marks the document FAILED and stops; the caller is a
    background task, so there is nobody left to report the error to. The
    file stays on disk either way, so `reprocess_document` can pick it up
    once whatever broke has been fixed.
    """

    try:
        attempt = record_attempt(document_id)
        set_status(document_id, STATUS_PROCESSING)

        chunks = build_chunks(document_id)

        embedding_count = embed_chunks(
            document_id,
            chunks,
        )

        # The summary is what stage 1 of hierarchical retrieval ranks
        # documents on — a filename alone is far too few words for BM25 to
        # separate one document from another. Best-effort even so: a model
        # failure must not throw away a document that is already chunked
        # and embedded, and reprocessing will fill the summary in later.
        summary_failure = None

        try:
            summarize_document(document_id)

        except Exception as summary_error:
            summary_failure = describe_failure(summary_error)

            logger.warning(
                "Could not summarise document %s (%s): %s",
                document_id,
                summary_failure["reason"],
                summary_failure["message"],
            )

        set_status(document_id, STATUS_READY)

        if summary_failure is not None:
            # READY, but flagged: the document is retrievable by chunk and
            # invisible to document-level ranking, which is worth surfacing
            # rather than leaving as a silently empty field.
            _record_summary_failure(document_id, summary_failure)

        logger.info(
            "Document %s processed on attempt %d: %d chunks, %d embeddings",
            document_id,
            attempt,
            len(chunks),
            embedding_count,
        )

    except Exception as exc:
        logger.exception(
            "Processing failed for document %s",
            document_id,
        )

        try:
            mark_failed(document_id, exc)

        except Exception:
            logger.exception(
                "Could not mark document %s as FAILED",
                document_id,
            )
