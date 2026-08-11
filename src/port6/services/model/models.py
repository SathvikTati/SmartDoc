from datetime import datetime
from uuid import uuid4

from sqlalchemy import BigInteger, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID

from port6.services.db.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    filename = Column(
        String,
        nullable=False
    )

    file_type = Column(
        String,
        nullable=False
    )

    size_bytes = Column(
        BigInteger,
        nullable=False
    )

    sha256 = Column(
        String(64),
        unique=True,
        nullable=False
    )

    content_sha256 = Column(
        String(64),
        unique=True,
        nullable=False
    )

    storage_path = Column(
        String,
        nullable=False
    )

    created_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow
    )