"""chats and conversation turns

Adds a conversation around question history so a follow-up can be resolved
against what came before. "What about sick leave?" is only answerable
relative to the previous turn; without a chat there is nothing to resolve
it against.

`query_runs.chat_id` is nullable so existing rows stay valid — they are
simply history that predates conversations.

Revision ID: c93a5f27e410
Revises: b8e2f4a10c37
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c93a5f27e410'
down_revision: Union[str, Sequence[str], None] = 'b8e2f4a10c37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chats',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('now()'),
        ),
    )

    # Chats list by recent activity, not by when they were started.
    op.create_index(
        'ix_chats_updated_at',
        'chats',
        [sa.text('updated_at DESC')],
    )

    op.add_column(
        'query_runs',
        sa.Column(
            'chat_id',
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        'query_runs',
        sa.Column(
            'turn_index',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
    )
    op.add_column(
        'query_runs',
        sa.Column('relation', sa.String(length=20), nullable=True),
    )
    op.add_column(
        'query_runs',
        sa.Column('standalone_question', sa.Text(), nullable=True),
    )
    op.add_column(
        'query_runs',
        sa.Column('context_strategy', sa.String(length=20), nullable=True),
    )

    op.create_foreign_key(
        'fk_query_runs_chat_id',
        'query_runs',
        'chats',
        ['chat_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.create_index('ix_query_runs_chat_id', 'query_runs', ['chat_id'])


def downgrade() -> None:
    op.drop_index('ix_query_runs_chat_id', table_name='query_runs')
    op.drop_constraint('fk_query_runs_chat_id', 'query_runs', type_='foreignkey')

    op.drop_column('query_runs', 'context_strategy')
    op.drop_column('query_runs', 'standalone_question')
    op.drop_column('query_runs', 'relation')
    op.drop_column('query_runs', 'turn_index')
    op.drop_column('query_runs', 'chat_id')

    op.drop_index('ix_chats_updated_at', table_name='chats')
    op.drop_table('chats')
