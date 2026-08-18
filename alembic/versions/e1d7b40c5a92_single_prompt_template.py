"""Collapse the prompt system/human pair into one template

The split mirrored the two chat turns, but every prompt in this system
ordered itself the same way anyway — instructions, then sources, then the
question — so the human half only ever held the last line or two, and an
edit meant keeping two fields consistent by hand.

Existing rows are joined rather than dropped: the two halves were always
concatenated in that order at render time, so the joined text produces the
same prompt the row produced before.

Revision ID: e1d7b40c5a92
Revises: c93a5f27e410
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e1d7b40c5a92"
down_revision = "c93a5f27e410"
branch_labels = None
depends_on = None


def upgrade() -> None:

    # Added nullable so the backfill has somewhere to write before the
    # NOT NULL constraint is applied.
    op.add_column(
        "prompts",
        sa.Column("template", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompts",
        sa.Column("default_template", sa.Text(), nullable=True),
    )

    op.execute(
        """
        UPDATE prompts
        SET template = system || E'\n\n' || human,
            default_template = default_system || E'\n\n' || default_human
        """
    )

    op.alter_column("prompts", "template", nullable=False)
    op.alter_column("prompts", "default_template", nullable=False)

    op.drop_column("prompts", "system")
    op.drop_column("prompts", "human")
    op.drop_column("prompts", "default_system")
    op.drop_column("prompts", "default_human")


def downgrade() -> None:
    """Reverses the schema, but not the join.

    Nothing records where the two halves met, so the whole template goes
    back into `system` and `human` becomes empty. Anything downgraded here
    should be re-seeded rather than trusted to be byte-identical.
    """

    op.add_column("prompts", sa.Column("system", sa.Text(), nullable=True))
    op.add_column("prompts", sa.Column("human", sa.Text(), nullable=True))
    op.add_column(
        "prompts",
        sa.Column("default_system", sa.Text(), nullable=True),
    )
    op.add_column(
        "prompts",
        sa.Column("default_human", sa.Text(), nullable=True),
    )

    op.execute(
        """
        UPDATE prompts
        SET system = template,
            human = '',
            default_system = default_template,
            default_human = ''
        """
    )

    for column in ("system", "human", "default_system", "default_human"):
        op.alter_column("prompts", column, nullable=False)

    op.drop_column("prompts", "template")
    op.drop_column("prompts", "default_template")
