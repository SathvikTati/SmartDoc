"""Widen the query run pipeline slug

A composition id is built from its parts — `agent[tool,tool]:a+b+c` — so
its length grows with the number of retrievers and tools it names. The
default composition alone reaches 62 characters, two past the original
60, and every run recorded under it was silently dropped: history
recording is best-effort, so the truncation error became a log line and
the answer came back looking fine.

Any fixed cap is the same guess made again, so this drops the cap. The
index stays; slugs are far short of a btree's limit.

Revision ID: a3f18d5c0b72
Revises: f2a91c6d80b4
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a3f18d5c0b72"
down_revision = "f2a91c6d80b4"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.alter_column(
        "query_runs",
        "pipeline",
        existing_type=sa.String(length=60),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:

    # Anything longer than the old cap would fail the narrowing, so it is
    # cleared first: the column is nullable, and a truncated slug names a
    # composition that never ran.
    op.execute(
        "UPDATE query_runs SET pipeline = NULL WHERE length(pipeline) > 60"
    )

    op.alter_column(
        "query_runs",
        "pipeline",
        existing_type=sa.Text(),
        type_=sa.String(length=60),
        existing_nullable=True,
    )
