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