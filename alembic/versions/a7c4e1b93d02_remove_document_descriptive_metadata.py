"""remove document descriptive metadata

Drops document_title, document_type and department. These were extracted
from each document's own content during ingestion, which cost an LLM call
per upload and produced a classification nothing could verify. Documents are
now identified by their filename, and citations read as
"hr_policy.md, Section 1.1 Annual Leave".

Revision ID: a7c4e1b93d02
Revises: cf61a0ac779f
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c4e1b93d02'
down_revision: Union[str, Sequence[str], None] = 'cf61a0ac779f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('documents', 'document_title')
    op.drop_column('documents', 'document_type')
    op.drop_column('documents', 'department')


def downgrade() -> None:
    # The columns come back empty: the values were derived at ingestion
    # time and are not recoverable without re-running extraction.
    op.add_column(
        'documents',
        sa.Column('department', sa.String(), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('document_type', sa.String(), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('document_title', sa.String(), nullable=True),
    )
