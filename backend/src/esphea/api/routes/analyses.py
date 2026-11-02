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
    TopologySeriesOut,
)
from esphea.services.errors import NotFoundError
from esphea.topology.clouds import NormalizationKind, PointCloudKind
from esphea.topology.config import TopologyAnalysisConfig

router = APIRouter(tags=["analyses"])


@router.get("/runs/{run_id}/analyses")
def list_analyses(run_id: uuid.UUID, service: AnalysisServiceDep) -> list[AnalysisOut]:
    return [AnalysisOut.from_row(row) for row in service.list_for_run(run_id)]


@router.post("/runs/{run_id}/analyses", status_code=status.HTTP_201_CREATED)
def create_analysis(
    run_id: uuid.UUID, config: TopologyAnalysisConfig, service: AnalysisServiceDep
) -> AnalysisOut:
    """Queue a persistent-homology analysis of every stored generation of a finished run."""
    return AnalysisOut.from_row(service.create(run_id, config))


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
