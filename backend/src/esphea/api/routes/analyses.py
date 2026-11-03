"""Run analysis endpoints (persistent homology)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from esphea.api.dependencies import AnalysisServiceDep
from esphea.api.topology_schemas import (
    AnalysisOut,
    BettiCurvesOut,
    DiagramOut,
    DistanceMatrixOut,
    EpsilonSuggestionOut,
    RepresentativeOut,
    TopologySeriesOut,
    ZigzagBarsOut,
    ZigzagBatchSummaryOut,
    ZigzagEventsOut,
)
from esphea.services.errors import NotFoundError
from esphea.topology.clouds import NormalizationKind, PointCloudKind
from esphea.topology.config import AnalysisConfig
from esphea.topology.zigzag_storage import filter_bars

router = APIRouter(tags=["analyses"])


@router.get("/runs/{run_id}/analyses")
def list_analyses(run_id: uuid.UUID, service: AnalysisServiceDep) -> list[AnalysisOut]:
    return [AnalysisOut.from_row(row) for row in service.list_for_run(run_id)]


@router.post("/runs/{run_id}/analyses", status_code=status.HTTP_201_CREATED)
def create_analysis(
    run_id: uuid.UUID, config: AnalysisConfig, service: AnalysisServiceDep
) -> AnalysisOut:
    """Queue an analysis (``topology`` or ``zigzag``) of a finished run."""
    return AnalysisOut.from_row(service.create(run_id, config))


@router.get("/experiments/{experiment_id}/analyses")
def list_experiment_analyses(
    experiment_id: uuid.UUID, service: AnalysisServiceDep
) -> list[AnalysisOut]:
    """Analyses of every run of an experiment (batches share a ``batch_id``)."""
    return [AnalysisOut.from_row(row) for row in service.list_for_experiment(experiment_id)]


@router.post("/experiments/{experiment_id}/analyses", status_code=status.HTTP_201_CREATED)
def create_analysis_batch(
    experiment_id: uuid.UUID, config: AnalysisConfig, service: AnalysisServiceDep
) -> list[AnalysisOut]:
    """Queue the same analysis for every finished run of an experiment, as one batch."""
    return [AnalysisOut.from_row(row) for row in service.create_batch(experiment_id, config)]


@router.get("/runs/{run_id}/epsilon-suggestion")
def suggest_epsilon(
    run_id: uuid.UUID,
    service: AnalysisServiceDep,
    point_cloud: PointCloudKind = PointCloudKind.SURVIVORS,
    normalization: NormalizationKind = NormalizationKind.NONE,
) -> EpsilonSuggestionOut:
    """Scale statistics of the run's point clouds to choose ``max_epsilon``."""
    return EpsilonSuggestionOut.from_suggestion(
        service.suggest_epsilon(run_id, point_cloud, normalization)
    )


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: uuid.UUID, service: AnalysisServiceDep) -> AnalysisOut:
    return AnalysisOut.from_row(service.get(analysis_id))


@router.delete("/analyses/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(analysis_id: uuid.UUID, service: AnalysisServiceDep) -> Response:
    service.delete(analysis_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/analyses/{analysis_id}/series")
def get_series(analysis_id: uuid.UUID, service: AnalysisServiceDep) -> TopologySeriesOut:
    """Per-generation summaries and distances (to the previous and to the final generation)."""
    return TopologySeriesOut.from_reader(service.results(analysis_id))


@router.get("/analyses/{analysis_id}/diagrams/{generation}")
def get_diagram(analysis_id: uuid.UUID, generation: int, service: AnalysisServiceDep) -> DiagramOut:
    try:
        diagram = service.results(analysis_id).diagram(generation)
    except KeyError as exc:
        raise NotFoundError(str(exc.args[0])) from None
    return DiagramOut.from_diagram(generation, diagram)


@router.get("/analyses/{analysis_id}/betti")
def get_betti_curves(
    analysis_id: uuid.UUID,
    service: AnalysisServiceDep,
    dimension: Annotated[int, Query(ge=0, le=2)] = 0,
    resolution: Annotated[int, Query(ge=10, le=500)] = 100,
) -> BettiCurvesOut:
    """Betti numbers per generation over the scale grid ``0..max_epsilon``."""
    reader = service.results(analysis_id)
    if dimension > reader.max_dimension:
        raise NotFoundError(f"H{dimension} was not computed")
    grid, curves = reader.betti_curves(dimension, resolution)
    return BettiCurvesOut(
        dimension=dimension,
        epsilon=grid.tolist(),
        generation=reader.generations,
        values=curves.tolist(),
    )


@router.get("/analyses/{analysis_id}/matrix")
def get_distance_matrix(
    analysis_id: uuid.UUID,
    service: AnalysisServiceDep,
    dimension: Annotated[int, Query(ge=0, le=2)] = 0,
    metric: str = "bottleneck",
) -> DistanceMatrixOut:
    try:
        generations, values = service.results(analysis_id).matrix(dimension, metric)
    except KeyError as exc:
        raise NotFoundError(str(exc.args[0])) from None
    return DistanceMatrixOut(
        dimension=dimension, metric=metric, generation=generations, values=values.tolist()
    )


# --- zigzag ---------------------------------------------------------------------------


@router.get("/analyses/{analysis_id}/zigzag/bars")
def get_zigzag_bars(
    analysis_id: uuid.UUID,
    service: AnalysisServiceDep,
    epsilon_index: Annotated[int, Query(ge=0)] = 0,
    dimension: Annotated[int, Query(ge=0, le=2)] = 0,
    min_lifetime: Annotated[int, Query(ge=1)] = 1,
) -> ZigzagBarsOut:
    reader = service.zigzag_results(analysis_id)
    try:
        table = filter_bars(reader.bars(epsilon_index, dimension), min_lifetime).to_pydict()
    except KeyError as exc:
        raise NotFoundError(str(exc.args[0])) from None
    available = reader.representative_bars(epsilon_index)
    return ZigzagBarsOut(
        epsilon=reader.epsilons[epsilon_index],
        dimension=dimension,
        n_generations=reader.n_generations,
        n_steps=reader.n_steps,
        bar=table["bar"],
        birth=table["birth"],
        death=table["death"],
        kind=table["kind"],
        birth_cause=table["birth_cause"],
        death_cause=table["death_cause"],
        representative=[available.get(b) for b in table["bar"]],
    )


@router.get("/analyses/{analysis_id}/zigzag/events")
def get_zigzag_events(
    analysis_id: uuid.UUID,
    service: AnalysisServiceDep,
    epsilon_index: Annotated[int, Query(ge=0)] = 0,
    dimension: Annotated[int, Query(ge=0, le=2)] = 0,
) -> ZigzagEventsOut:
    reader = service.zigzag_results(analysis_id)
    try:
        events = reader.events(epsilon_index, dimension)
        betti = reader.betti(epsilon_index, dimension).tolist()
    except KeyError as exc:
        raise NotFoundError(str(exc.args[0])) from None
    return ZigzagEventsOut(
        epsilon=reader.epsilons[epsilon_index],
        dimension=dimension,
        generation=list(range(reader.n_generations + 1)),
        betti_p=betti[0::2],
        betti_r=[None, *betti[1::2]],
        births_variation=events.births_variation.tolist(),
        births_selection=events.births_selection.tolist(),
        deaths_variation=events.deaths_variation.tolist(),
        deaths_selection=events.deaths_selection.tolist(),
    )


@router.get("/analyses/{analysis_id}/zigzag/representative")
def get_zigzag_representative(
    analysis_id: uuid.UUID,
    service: AnalysisServiceDep,
    bar: int,
    step: Annotated[int, Query(ge=0)],
    epsilon_index: Annotated[int, Query(ge=0)] = 0,
) -> RepresentativeOut:
    """The population at ``step`` and the representative cycle of ``bar`` there."""
    return RepresentativeOut.from_view(
        service.zigzag_representative(analysis_id, epsilon_index, bar, step)
    )


@router.get("/analysis-batches/{batch_id}/zigzag-summary")
def get_zigzag_batch_summary(
    batch_id: uuid.UUID,
    service: AnalysisServiceDep,
    epsilon_index: Annotated[int, Query(ge=0)] = 0,
    dimension: Annotated[int, Query(ge=0, le=2)] = 0,
) -> ZigzagBatchSummaryOut:
    """Median and quartiles across the runs of a batch, per generation."""
    return ZigzagBatchSummaryOut.from_summary(
        service.zigzag_batch_summary(batch_id, epsilon_index, dimension)
    )
