"""Record which retrieval pipeline answered a query run

`mode` is the family — naive, hybrid, agentic — and stays. It is not
enough on its own now that a family holds several strategies: "hybrid"
could mean semantic and keyword, hierarchical and keyword, or all three,
and comparing them is the point of having them.

Nullable, because every run recorded before this existed has a mode and
no pipeline, and inventing one for them would be a guess.

Revision ID: f2a91c6d80b4
Revises: e1d7b40c5a92
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "f2a91c6d80b4"
down_revision = "e1d7b40c5a92"
branch_labels = None
depends_on = None


def upgrade() -> None:

    op.add_column(
        "query_runs",
        sa.Column("pipeline", sa.String(length=60), nullable=True),
    )

    # Indexed because the obvious question of this table is "how did
    # pipeline X do", which is a filter on this column.
    op.create_index(
        "ix_query_runs_pipeline",
        "query_runs",
        ["pipeline"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_runs_pipeline", table_name="query_runs")
    op.drop_column("query_runs", "pipeline")
