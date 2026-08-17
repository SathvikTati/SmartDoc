"""settings, prompts, query history and ingestion attempts

Four additions:

- `settings` and `prompts` hold the values that used to be hardcoded, so
  tuning and prompt wording can change without a redeploy. Rows are seeded
  by the application on startup, not here — the defaults live in Python so
  a fresh database and an upgraded one converge on the same content.
- `query_runs` persists each question and its full result, so history
  survives a browser refresh and retrieval behaviour can be reviewed later.
- `documents.attempts` / `last_attempt_at` / `failure_kind` support
  reprocessing: a FAILED document keeps its file, so it can be retried once
  whatever broke is fixed.

Revision ID: b8e2f4a10c37
Revises: a7c4e1b93d02
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b8e2f4a10c37'
down_revision: Union[str, Sequence[str], None] = 'a7c4e1b93d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'settings',
        sa.Column('key', sa.String(length=80), primary_key=True),
        sa.Column('value', postgresql.JSONB(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('default_value', postgresql.JSONB(), nullable=True),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_table(
        'prompts',
        sa.Column('name', sa.String(length=80), primary_key=True),
        sa.Column('system', sa.Text(), nullable=False),
        sa.Column('human', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column(
            'variables',
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            'version',
            sa.Integer(),
            nullable=False,
            server_default='1',
        ),
        sa.Column('default_system', sa.Text(), nullable=False),
        sa.Column('default_human', sa.Text(), nullable=False),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    op.create_table(
        'query_runs',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('mode', sa.String(length=20), nullable=False),
        sa.Column('top_k', sa.Integer(), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('answered', sa.Boolean(), nullable=False),
        sa.Column('citation_count', sa.Integer(), nullable=False),
        sa.Column('chunk_count', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Float(), nullable=True),
        sa.Column('retrieval_method', sa.Text(), nullable=True),
        sa.Column('result', postgresql.JSONB(), nullable=False),
        sa.Column('prompt_versions', postgresql.JSONB(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    # History is read newest-first, always.
    op.create_index(
        'ix_query_runs_created_at',
        'query_runs',
        [sa.text('created_at DESC')],
    )

    op.add_column(
        'documents',
        sa.Column(
            'attempts',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'documents',
        sa.Column('last_attempt_at', sa.DateTime(), nullable=True),
    )
    op.add_column(
        'documents',
        sa.Column('failure_kind', sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('documents', 'failure_kind')
    op.drop_column('documents', 'last_attempt_at')
    op.drop_column('documents', 'attempts')

    op.drop_index('ix_query_runs_created_at', table_name='query_runs')
    op.drop_table('query_runs')
    op.drop_table('prompts')
    op.drop_table('settings')
