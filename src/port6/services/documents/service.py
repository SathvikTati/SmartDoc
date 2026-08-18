from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from port6.services.model.models import Document
from port6.services.schemas.document import (
    DocumentResponse,
    DocumentSection,
    DocumentStructureResponse,
)
from port6.services.structure.service import build_sections
from port6.services.vector.chroma import (
    count_chunks_by_document,
    count_document_chunks,
    delete_document_chunks,
)


def get_documents(db: Session) -> list[DocumentResponse]:
    """Every document, each carrying its chunk count.

    The count comes from one tally over the index rather than a query per
    row, and is attached here rather than stored on the document, so it
    cannot drift from what is actually searchable.
    """

    documents = (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .all()
    )

    counts = count_chunks_by_document()

    listed = []

    for document in documents:

        response = DocumentResponse.model_validate(document)
        response.chunk_count = counts.get(str(document.id), 0)

        listed.append(response)

    return listed


def get_document(
    db: Session,
    document_id: UUID,
) -> Document:
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return document


def get_document_content(
    db: Session,
    document_id: UUID,
) -> Document:
    return get_document(db, document_id)


def get_document_summary(
    db: Session,
    document_id: UUID,
) -> Document:
    return get_document(db, document_id)


def get_document_structure(
    db: Session,
    document_id: UUID,
) -> DocumentStructureResponse:
    """The document's heading tree, plus how much of it was indexed.

    Only the plain text is kept in Postgres, so the headings have to be
    recovered by re-parsing the stored file — the same thing ingestion does.
    If that file is gone the document is still perfectly queryable, so this
    reports `structure_available: false` rather than failing.
    """

    # Imported here rather than at module scope: this is the only caller,
    # and it keeps the documents service from pulling in the whole
    # ingestion pipeline just to list documents.
    from port6.services.ingestion.service import load_blocks

    document = get_document(db, document_id)

    blocks = load_blocks(document)

    sections = [
        DocumentSection(
            section_id=section.section_id,
            title=section.title,
            level=section.level,
            parent_section_id=section.parent_section_id,
            path=section.path,
            has_content=bool(section.blocks),
            character_count=len(section.text),
            page_start=section.page_start,
            page_end=section.page_end,
        )
        for section in build_sections(blocks)
    ]

    pages = [
        block.page_number
        for block in blocks
        if block.page_number is not None
    ]

    return DocumentStructureResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        chunk_count=count_document_chunks(str(document.id)),
        page_count=max(pages) if pages else None,
        character_count=len(document.content or ""),
        sections=sections,
        structure_available=bool(blocks),
    )


def documents_needing_attention(
    db: Session,
) -> list[Document]:
    """Documents that did not fully ingest and could be retried.

    Two cases, both recoverable: an outright FAILED document, and one that
    reached READY without a summary — retrievable by chunk, but invisible
    to document-level ranking until it is summarised.
    """

    return (
        db.query(Document)
        .filter(
            (Document.status == "FAILED")
            | ((Document.status == "READY") & (Document.summary.is_(None)))
        )
        .order_by(Document.created_at.desc())
        .all()
    )


def prepare_reprocess(
    db: Session,
    document_id: UUID,
) -> Document:
    """Check a document can be reprocessed, and clear its previous failure.

    The uploaded file is never deleted on failure, which is what makes a
    retry possible at all: whatever broke — a stopped Ollama, an expired
    key — can be fixed and the same bytes run through again.
    """

    document = get_document(db, document_id)

    storage_path = Path(document.storage_path)

    if not storage_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The stored file for this document is gone, so it cannot "
                "be reprocessed. Upload it again."
            ),
        )

    if document.status == "PROCESSING":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is already being processed.",
        )

    document.status = "UPLOADED"
    document.error_message = None
    document.failure_kind = None

    db.commit()
    db.refresh(document)

    return document


def delete_document(
    db: Session,
    document_id: UUID,
):
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found",
        )

    storage_path = Path(document.storage_path)

    try:
        # 1. Delete embeddings/chunks
        delete_document_chunks(
            str(document.id)
        )

        # 2. Delete physical file
        storage_path.unlink(
            missing_ok=True
        )

        # 3. Delete PostgreSQL record
        db.delete(document)
        db.commit()

        return document

    except Exception as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Could not delete document: {str(exc)}"
            ),
        )