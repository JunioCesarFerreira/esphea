"""Relational schema: experiments, their runs and per-generation metrics.

Bulk population data does not live here but in Parquet snapshots
(:mod:`esphea.experiments.storage`).
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonType = JSON().with_variant(JSONB(), "postgresql")


def _enum_values(enum: type[StrEnum]) -> list[str]:
    return [member.value for member in enum]


class Base(DeclarativeBase):
    pass


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (RunStatus.QUEUED, RunStatus.RUNNING)


class ExperimentRow(Base):
    __tablename__ = "experiments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict[str, Any]] = mapped_column(JsonType)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    runs: Mapped[list["RunRow"]] = relationship(
        back_populates="experiment",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RunRow.index",
    )


class RunRow(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("experiment_id", "index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False, length=16, values_callable=_enum_values),
        default=RunStatus.QUEUED,
    )
    generation: Mapped[int] = mapped_column(Integer, default=0)
    # Execution attempt that owns the run (0 = never claimed). Every write made by a
    # worker is fenced by it, so a worker that lost the run cannot corrupt a retry.
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Lease renewed by the executing worker; a stale lease means the worker is gone.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    experiment: Mapped[ExperimentRow] = relationship(back_populates="runs")


class RunMetricRow(Base):
    __tablename__ = "run_metrics"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    n_nondominated: Mapped[int] = mapped_column(Integer)
    elapsed_seconds: Mapped[float] = mapped_column(Float)
    # Indicator name -> value. JSON keeps the schema open to new indicators.
    values: Mapped[dict[str, float]] = mapped_column(JsonType)
