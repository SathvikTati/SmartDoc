from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from port6.services.model.models import Document


def get_documents(db: Session) -> list[Document]:
    return (
        db.query(Document)
        .order_by(Document.created_at.desc())
        .all()
    )


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


from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from port6.services.model.models import Document
from port6.services.vector.chroma import delete_document_chunks


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