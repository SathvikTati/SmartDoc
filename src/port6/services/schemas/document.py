from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from port6.services.schemas.common import UtcDatetime


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    content_sha256: str
    storage_path: str
    status: str
    created_at: UtcDatetime
    summary: str | None = None
    error_message: str | None = None

    # Ingestion attempts. `failure_kind` is one of provider | parse |
    # storage | unknown, and is what tells a client whether retrying is
    # likely to help.
    attempts: int = 0
    last_attempt_at: UtcDatetime | None = None
    failure_kind: str | None = None

    # How many chunks this document currently has in the vector index.
    # Filled on the list endpoint from one bulk tally; 0 elsewhere rather
    # than a Chroma round trip per document.
    chunk_count: int = 0

    model_config = ConfigDict(
        from_attributes=True
    )


class DocumentSummaryResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    summary: str | None = None

    model_config = ConfigDict(
        from_attributes=True
    )


class DocumentContentResponse(BaseModel):
    id: UUID
    filename: str
    content: str

    model_config = ConfigDict(
        from_attributes=True
    )


class DocumentSection(BaseModel):
    """One node of a document's heading tree, flattened.

    The tree is sent flat with `level` and `parent_section_id` rather than
    nested, because that is also how chunks carry their section metadata —
    a client can join the two without reshaping either.
    """

    section_id: str
    title: str
    level: int
    parent_section_id: str | None = None
    path: list[str] = []

    # Sections that only hold subsections have no text of their own.
    has_content: bool = False
    character_count: int = 0

    page_start: int | None = None
    page_end: int | None = None


class DocumentStructureResponse(BaseModel):
    id: UUID
    filename: str
    status: str

    chunk_count: int = 0
    page_count: int | None = None
    character_count: int = 0

    sections: list[DocumentSection] = []

    # False when the stored file is gone, so structure could not be re-read.
    structure_available: bool = True