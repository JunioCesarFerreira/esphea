"""HTTP response models of run analyses."""

import math
import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from esphea.persistence.models import AnalysisRow, RunStatus
from esphea.services.analyses import (
    AnalysisGroup,
    EpsilonSuggestion,
    GroupSummary,
    RepresentativeView,
    TrackerBarsView,
    TrackerComparison,
    TrackerRuns,
    ZigzagBatchSummary,
)
from esphea.topology.config import AnalysisConfig, parse_analysis_config
from esphea.topology.diagram import PersistenceDiagram
from esphea.topology.storage import TopologyResultReader
from esphea.topology.trackers import TrackerMethod


def _optional(values: list[float]) -> list[float | None]:
    """NaN (undefined, e.g. no previous generation) -> null."""
    return [None if math.isnan(v) else v for v in values]


class AnalysisOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    batch_id: uuid.UUID | None
    kind: str
    config: AnalysisConfig
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
            batch_id=row.batch_id,
            kind=row.kind,
            config=parse_analysis_config(row.kind, row.config),
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
    suggested_scales: list[float] = Field(
        description="Fixed scales for a zigzag: multiples of the population's spacing."
    )

    @classmethod
    def from_suggestion(cls, suggestion: EpsilonSuggestion) -> Self:
        return cls(
            max_diameter=suggestion.max_diameter,
            median_diameter=suggestion.median_diameter,
            median_nearest_neighbour=suggestion.median_nearest_neighbour,
            suggested_max_epsilon=suggestion.suggested_max_epsilon,
            suggested_scales=suggestion.suggested_scales,
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


# --- zigzag ---------------------------------------------------------------------------


class ZigzagBarsOut(BaseModel):
    """Bars alive on steps [birth, death - 1]; step 2t is P_t and step 2t - 1 is R_t."""

    epsilon: float
    dimension: int
    n_generations: int
    n_steps: int
    n_simplices: int | None
    representatives_skipped: str | None = Field(
        description="Why representatives were not extracted at this scale (null otherwise)."
    )
    bar: list[int]
    birth: list[int]
    death: list[int]
    kind: list[str]
    birth_cause: list[str]
    death_cause: list[str]
    representative: list[bool | None] = Field(
        description="Representative available (true), unavailable (false) or not kept (null)."
    )


class ZigzagEventsOut(BaseModel):
    """Per generation t: Betti numbers at P_t and R_t, births and deaths by cause."""

    epsilon: float
    dimension: int
    generation: list[int]
    betti_p: list[int]
    betti_r: list[int | None]
    births_variation: list[int]
    births_selection: list[int]
    deaths_variation: list[int]
    deaths_selection: list[int]


class RepresentativeOut(BaseModel):
    step: int
    generation: int
    is_r_step: bool
    dimension: int
    members: list[int]
    points: list[list[float]]
    simplices: list[list[int]] | None
    component: list[int]

    @classmethod
    def from_view(cls, view: RepresentativeView) -> Self:
        return cls(
            step=view.step,
            generation=view.generation,
            is_r_step=view.is_r_step,
            dimension=view.dimension,
            members=view.members.tolist(),
            points=view.points.tolist(),
            simplices=view.simplices,
            component=view.component.tolist(),
        )


class QuartilesOut(BaseModel):
    q1: list[float]
    median: list[float]
    q3: list[float]


class ZigzagBatchSummaryOut(BaseModel):
    generation: list[int]
    n_runs: int
    series: dict[str, QuartilesOut]

    @classmethod
    def from_summary(cls, summary: ZigzagBatchSummary) -> Self:
        return cls(
            generation=summary.generations,
            n_runs=summary.n_runs,
            series={
                name: QuartilesOut(q1=q.q1.tolist(), median=q.median.tolist(), q3=q.q3.tolist())
                for name, q in summary.series.items()
            },
        )


class AnalysisGroupOut(BaseModel):
    """Analyses of an experiment's runs that share a configuration."""

    key: str
    kind: str
    config: AnalysisConfig
    analysis_ids: list[uuid.UUID] = Field(description="Newest completed analysis of each run.")
    runs: int = Field(description="Runs with a completed analysis.")
    pending: int = Field(description="Runs whose analysis is still queued or running.")
    created_at: datetime

    @classmethod
    def from_group(cls, group: AnalysisGroup) -> Self:
        return cls(
            key=group.key,
            kind=group.kind,
            config=parse_analysis_config(group.kind, group.config),
            analysis_ids=[a.id for a in group.completed],
            runs=len(group.completed),
            pending=group.pending,
            created_at=group.created_at,
        )


class SeriesQuartilesOut(BaseModel):
    q1: list[float | None]
    median: list[float | None]
    q3: list[float | None]


class SpreadOut(BaseModel):
    q1: float
    median: float
    q3: float


class AnalysisGroupSummaryOut(BaseModel):
    kind: str
    generation: list[int]
    n_runs: list[int] = Field(description="Runs contributing to each generation.")
    series: dict[str, SeriesQuartilesOut] = Field(
        description="Per generation; null where no run has a value (e.g. no previous generation)."
    )
    totals: dict[str, SpreadOut] = Field(
        description="Spread of the per-run totals of the event series (zigzag only)."
    )

    @classmethod
    def from_summary(cls, summary: GroupSummary) -> Self:
        return cls(
            kind=summary.kind,
            generation=summary.generations,
            n_runs=summary.n_runs,
            series={
                name: SeriesQuartilesOut(
                    q1=_optional(q.q1.tolist()),
                    median=_optional(q.median.tolist()),
                    q3=_optional(q.q3.tolist()),
                )
                for name, q in summary.series.items()
            },
            totals={
                name: SpreadOut(q1=t.q1, median=t.median, q3=t.q3)
                for name, t in summary.totals.items()
            },
        )


# --- niche trackers -------------------------------------------------------------------


class TrackerBarsOut(BaseModel):
    """H0 bars of a niche tracker, in zigzag steps, and whether the zigzag has the same bar."""

    epsilon: float
    method: TrackerMethod
    n_generations: int
    n_steps: int
    birth: list[int]
    death: list[int]
    matched_step: list[bool] = Field(
        description="The zigzag H0 barcode has a bar with the same birth and death steps."
    )
    matched_generation: list[bool] = Field(
        description="The zigzag H0 barcode has a bar born and ending in the same generations."
    )

    @classmethod
    def from_view(cls, view: TrackerBarsView) -> Self:
        return cls(
            epsilon=view.epsilon,
            method=view.method,
            n_generations=view.n_generations,
            n_steps=view.n_steps,
            birth=view.bars[:, 0].tolist(),
            death=view.bars[:, 1].tolist(),
            matched_step=view.matched_step.tolist(),
            matched_generation=view.matched_generation.tolist(),
        )


class MethodSummaryOut(BaseModel):
    """One method's H0 barcode of a run, and the share of the zigzag bars it reproduces."""

    method: str = Field(description="'zigzag' or a tracker: 't1', 't1o' or 't2'.")
    n_bars: int
    n_long: int = Field(description="Bars alive at least long_lifetime steps.")
    median_lifetime: float | None = Field(description="Steps; bars ending before the last step.")
    p90_lifetime: float | None
    agreement_step: float | None = Field(
        description="Share of the zigzag bars with a bar of the same birth and death steps."
    )
    agreement_generation: float | None = Field(
        description="Share of the zigzag bars with a bar of the same birth and death generations."
    )
    long_agreement_step: float | None = Field(
        description="The same for the long zigzag bars (null when there is none)."
    )
    long_agreement_generation: float | None
    at_least: list[int] = Field(description="Bars alive at least L steps, for L = 1 .. n_steps.")


class TrackerComparisonOut(BaseModel):
    epsilon: float
    n_generations: int
    n_steps: int
    long_lifetime: int
    methods: list[MethodSummaryOut] = Field(description="The zigzag first, then the trackers.")

    @classmethod
    def from_comparison(cls, comparison: TrackerComparison) -> Self:
        return cls(
            epsilon=comparison.epsilon,
            n_generations=comparison.n_generations,
            n_steps=comparison.n_steps,
            long_lifetime=comparison.long_lifetime,
            methods=[
                MethodSummaryOut(
                    method=m.method,
                    n_bars=m.n_bars,
                    n_long=m.n_long,
                    median_lifetime=m.median_lifetime,
                    p90_lifetime=m.p90_lifetime,
                    agreement_step=m.agreement_step,
                    agreement_generation=m.agreement_generation,
                    long_agreement_step=m.long_agreement_step,
                    long_agreement_generation=m.long_agreement_generation,
                    at_least=m.at_least,
                )
                for m in comparison.methods
            ],
        )


class MethodRunsOut(BaseModel):
    """One value per run, in run order (see MethodSummaryOut for the meaning)."""

    n_bars: list[float | None]
    n_long: list[float | None]
    median_lifetime: list[float | None]
    p90_lifetime: list[float | None]
    agreement_step: list[float | None]
    agreement_generation: list[float | None]
    long_agreement_step: list[float | None]
    long_agreement_generation: list[float | None]


class TrackerRunsOut(BaseModel):
    epsilon: float
    long_lifetime: int
    n_runs: int
    skipped: int = Field(description="Runs whose analysis predates the niche trackers.")
    methods: dict[str, MethodRunsOut] = Field(description="'zigzag', 't1', 't1o' and 't2'.")

    @classmethod
    def from_runs(cls, runs: TrackerRuns) -> Self:
        return cls(
            epsilon=runs.epsilon,
            long_lifetime=runs.long_lifetime,
            n_runs=runs.n_runs,
            skipped=runs.skipped,
            methods={
                name: MethodRunsOut.model_validate(fields) for name, fields in runs.methods.items()
            },
        )
