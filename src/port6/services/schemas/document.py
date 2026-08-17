from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    id: UUID
    filename: str
    file_type: str
    size_bytes: int
    sha256: str
    content_sha256: str
    storage_path: str
    status: str
    created_at: datetime
    summary: str | None = None
    error_message: str | None = None

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