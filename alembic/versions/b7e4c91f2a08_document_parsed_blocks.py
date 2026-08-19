"""Keep the parser's output on the document

Only the plain text was stored, so headings and page numbers had to be
recovered by re-parsing the file — during chunking, and again on every view
of the structure page. Wasteful but harmless while parsing was a few
milliseconds of text extraction.

OCR changes that arithmetic. Re-parsing a scanned document means re-running
OCR on every page of it, so rendering a list of section titles would cost
what the original ingestion cost. Storing the blocks once removes the
repeat entirely.

Nullable: every document ingested before this has none, and `load_blocks`
already reports missing structure rather than failing on it.

Revision ID: b7e4c91f2a08
Revises: a3f18d5c0b72
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "b7e4c91f2a08"
down_revision = "a3f18d5c0b72"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.add_column(
        "documents",
        sa.Column(
            "blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:

    # Nothing is lost that cannot be recomputed: the file is still on disk,
    # and re-parsing it is exactly what the code did before this column.
    op.drop_column("documents", "blocks")
