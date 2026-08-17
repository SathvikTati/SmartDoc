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
from pathlib import Path

from langchain_core.documents import Document as LangChainDocument
from langchain_core.prompts import ChatPromptTemplate

from port6.config import summary_config
from port6.services.chunking.service import chunk_document
from port6.services.db.database import SessionLocal
from port6.services.llm.service import get_chat_model
from port6.services.model.models import Document
from port6.services.parsers.parser import ParsedBlock, parse
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
    error_message: str,
) -> None:
    """Record a failure without raising if the document has since vanished."""

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
            return

        document.status = STATUS_FAILED
        document.error_message = error_message

        db.commit()

        logger.error(
            "Document %s marked as FAILED: %s",
            document_id,
            error_message,
        )

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


def summarize_document(
    document_id: str,
) -> str:

    db = SessionLocal()

    try:
        document = _load_document(db, document_id)

        content = (document.content or "").strip()

        if not content:
            raise ValueError(
                f"Document {document_id} has no content to summarise"
            )

        max_characters = int(
            summary_config.get(
                "max_input_characters",
                12000,
            )
        )

        truncated = content[:max_characters]

        if len(content) > max_characters:
            logger.info(
                "Document %s truncated from %d to %d characters "
                "for summarisation",
                document_id,
                len(content),
                max_characters,
            )

        max_words = int(
            summary_config.get(
                "max_words",
                150,
            )
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    """
You are a document summarisation assistant.

Summarise the document below in at most
{max_words} words.

Rules:
- Use only what the document says.
- Do not invent information.
- Write plain prose, no bullet points or headings.
- Do not mention these instructions.

Document: {filename}

{content}
""",
                ),
                (
                    "human",
                    "Summarise this document.",
                ),
            ]
        )

        chain = prompt | get_chat_model()

        response = chain.invoke(
            {
                "filename": document.filename,
                "content": truncated,
                "max_words": max_words,
            }
        )

        summary = response.content

        if not isinstance(summary, str):
            summary = str(summary)

        summary = summary.strip()

        document.summary = summary

        db.commit()

        logger.info(
            "Summarised document %s (%d characters)",
            document_id,
            len(summary),
        )

        return summary

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


def process_document(
    document_id: str,
) -> None:
    """Take one uploaded document all the way to READY.

    Any failure marks the document FAILED and stops; the caller is a
    background task, so there is nobody left to report the error to.
    """

    try:
        set_status(document_id, STATUS_PROCESSING)

        chunks = build_chunks(document_id)

        embedding_count = embed_chunks(
            document_id,
            chunks,
        )

        # The summary is what stage 1 of hierarchical retrieval ranks
        # documents on — a filename alone is far too few words for BM25 to
        # separate one document from another. So a document without one is
        # still searchable by chunk, but much harder to select as a whole.
        # Best-effort even so: a model failure must not fail an otherwise
        # ingested document.
        try:
            summarize_document(document_id)

        except Exception as summary_error:
            logger.warning(
                "Could not summarise document %s: %s",
                document_id,
                summary_error,
            )

        set_status(document_id, STATUS_READY)

        logger.info(
            "Document %s processed successfully: "
            "%d chunks, %d embeddings",
            document_id,
            len(chunks),
            embedding_count,
        )

    except Exception as exc:
        logger.exception(
            "Processing failed for document %s",
            document_id,
        )

        try:
            mark_failed(document_id, str(exc))

        except Exception:
            logger.exception(
                "Could not mark document %s as FAILED",
                document_id,
            )
