"""HTTP response models of run analyses."""

import math
import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from esphea.persistence.models import AnalysisRow, RunStatus
from esphea.services.analyses import EpsilonSuggestion
from esphea.topology.config import TopologyAnalysisConfig
from esphea.topology.diagram import PersistenceDiagram
from esphea.topology.storage import TopologyResultReader


def _optional(values: list[float]) -> list[float | None]:
    """NaN (undefined, e.g. no previous generation) -> null."""
    return [None if math.isnan(v) else v for v in values]


class AnalysisOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    kind: str
    config: TopologyAnalysisConfig
    status: RunStatus
    progress: int
    total: int
    attempt: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None

    @classmethod
    def from_row(cls, row: AnalysisRow) -> Self:
        return cls(
            id=row.id,
            run_id=row.run_id,
            kind=row.kind,
            config=TopologyAnalysisConfig.model_validate(row.config),
            status=row.status,
            progress=row.progress,
            total=row.total,
            attempt=row.attempt,
            created_at=row.created_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            error=row.error,
        )


class EpsilonSuggestionOut(BaseModel):
    max_diameter: float
    median_diameter: float
    median_nearest_neighbour: float
    suggested_max_epsilon: float

    @classmethod
    def from_suggestion(cls, suggestion: EpsilonSuggestion) -> Self:
        return cls(
            max_diameter=suggestion.max_diameter,
            median_diameter=suggestion.median_diameter,
            median_nearest_neighbour=suggestion.median_nearest_neighbour,
            suggested_max_epsilon=suggestion.suggested_max_epsilon,
        )


class BarsOut(BaseModel):
    dimension: int
    birth: list[float]
    death: list[float]
    truncated: list[bool] = Field(description="Alive at max_epsilon (death capped at it).")


class DiagramOut(BaseModel):
    generation: int
    max_epsilon: float
    dimensions: list[BarsOut]

    @classmethod
    def from_diagram(cls, generation: int, diagram: PersistenceDiagram) -> Self:
        return cls(
            generation=generation,
            max_epsilon=diagram.max_epsilon,
            dimensions=[
                BarsOut(
                    dimension=k,
                    birth=bars[:, 0].tolist(),
                    death=bars[:, 1].tolist(),
                    truncated=diagram.truncated[k].tolist(),
                )
                for k, bars in enumerate(diagram.bars)
            ],
        )


class DistanceSeriesOut(BaseModel):
    previous: list[float | None] = Field(description="To the previous stored generation.")
    final: list[float] = Field(description="To the final generation.")


class DimensionSeriesOut(BaseModel):
    dimension: int
    n_bars: list[int]
    total_persistence: list[float]
    persistent_entropy: list[float]
    distances: dict[str, DistanceSeriesOut]


class TopologySeriesOut(BaseModel):
    generation: list[int]
    n_points: list[int]
    diameter: list[float]
    hausdorff_previous: list[float | None]
    hausdorff_final: list[float]
    max_finite_death: float = Field(
        description="Largest death of a feature not alive at max_epsilon, over all generations."
    )
    dimensions: list[DimensionSeriesOut]

    @classmethod
    def from_reader(cls, reader: TopologyResultReader) -> Self:
        clouds = reader.clouds().to_pydict()
        series = reader.series().to_pydict()
        dimensions = []
        for k in range(reader.max_dimension + 1):
            rows = [i for i, d in enumerate(series["dimension"]) if d == k]

            def column(name: str, rows: list[int] = rows) -> list[float]:
                return [series[name][i] for i in rows]

            dimensions.append(
                DimensionSeriesOut(
                    dimension=k,
                    n_bars=[int(v) for v in column("n_bars")],
                    total_persistence=column("total_persistence"),
                    persistent_entropy=column("persistent_entropy"),
                    distances={
                        metric: DistanceSeriesOut(
                            previous=_optional(column(f"{metric}_previous")),
                            final=column(f"{metric}_final"),
                        )
                        for metric in reader.metrics
                    },
                )
            )
        return cls(
            generation=clouds["generation"],
            n_points=clouds["n_points"],
            diameter=clouds["diameter"],
            hausdorff_previous=_optional(clouds["hausdorff_previous"]),
            hausdorff_final=clouds["hausdorff_final"],
            max_finite_death=reader.max_finite_death(),
            dimensions=dimensions,
        )


class BettiCurvesOut(BaseModel):
    dimension: int
    epsilon: list[float]
    generation: list[int]
    values: list[list[int]] = Field(
        description="values[i][j]: Betti number at generation i, scale j."
    )


class DistanceMatrixOut(BaseModel):
    dimension: int
    metric: str
    generation: list[int]
    values: list[list[float]]
