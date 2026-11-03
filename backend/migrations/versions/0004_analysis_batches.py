"""Analysis batches: analyses created together for every run of an experiment.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.create_index("ix_analyses_batch_id", "analyses", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_analyses_batch_id", table_name="analyses")
    op.drop_column("analyses", "batch_id")
