"""Run leases: execution attempts, heartbeats and enqueue time.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("attempt", sa.Integer(), server_default="0", nullable=False))
    op.add_column("runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("runs", sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True))
    # Runs that already executed did so once; everything counts as enqueued now.
    op.execute("UPDATE runs SET attempt = 1 WHERE status <> 'queued'")
    op.execute("UPDATE runs SET enqueued_at = CURRENT_TIMESTAMP")


def downgrade() -> None:
    op.drop_column("runs", "enqueued_at")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "attempt")
