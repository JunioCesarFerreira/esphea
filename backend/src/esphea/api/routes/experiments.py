"""Experiment endpoints (REST and real-time events)."""

import asyncio
import contextlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, WebSocket, WebSocketDisconnect, status

from esphea.api.dependencies import (
    ExperimentServiceDep,
    InfrastructureDep,
    ResultsServiceDep,
    SessionDep,
)
from esphea.api.schemas import (
    CatalogOut,
    ExperimentOut,
    ExperimentPreviewOut,
    ExperimentSummaryOut,
    IndicatorSummaryOut,
    ParetoFrontOut,
    default_catalog,
)
from esphea.experiments.config import ExperimentConfig
from esphea.persistence.repositories import ExperimentRepository

router = APIRouter(tags=["experiments"])


@router.get("/catalog")
def get_catalog() -> CatalogOut:
    """Problems and algorithms available, with default parameters."""
    return default_catalog()


@router.post("/experiments/preview")
def preview_experiment(config: ExperimentConfig) -> ExperimentPreviewOut:
    """Validate a configuration and return the quantities derived from it."""
    return ExperimentPreviewOut.from_config(config)


@router.post("/experiments", status_code=status.HTTP_201_CREATED)
def create_experiment(config: ExperimentConfig, service: ExperimentServiceDep) -> ExperimentOut:
    return ExperimentOut.from_row(service.create(config))


@router.get("/experiments")
def list_experiments(session: SessionDep) -> list[ExperimentSummaryOut]:
    return [ExperimentSummaryOut.from_row(row) for row in ExperimentRepository(session).list()]


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: uuid.UUID, service: ExperimentServiceDep) -> ExperimentOut:
    return ExperimentOut.from_row(service.get(experiment_id))


@router.post("/experiments/{experiment_id}/cancel")
def cancel_experiment(experiment_id: uuid.UUID, service: ExperimentServiceDep) -> ExperimentOut:
    return ExperimentOut.from_row(service.cancel(experiment_id))


@router.delete("/experiments/{experiment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_experiment(experiment_id: uuid.UUID, service: ExperimentServiceDep) -> Response:
    service.delete(experiment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/experiments/{experiment_id}/metrics")
def get_experiment_metrics(
    experiment_id: uuid.UUID, service: ResultsServiceDep
) -> dict[str, IndicatorSummaryOut]:
    """Median and quartiles of each indicator across runs, per generation."""
    return {
        name: IndicatorSummaryOut.from_summary(summary)
        for name, summary in service.experiment_metrics(experiment_id).items()
    }


@router.get("/experiments/{experiment_id}/pareto-front")
def get_pareto_front(
    experiment_id: uuid.UUID,
    service: ResultsServiceDep,
    n_points: Annotated[int, Query(ge=10, le=20_000)] = 1000,
) -> ParetoFrontOut:
    front = service.pareto_front(experiment_id, n_points)
    return ParetoFrontOut(points=None if front is None else front.tolist())


@router.websocket("/experiments/{experiment_id}/events")
async def experiment_events(
    websocket: WebSocket, experiment_id: uuid.UUID, infrastructure: InfrastructureDep
) -> None:
    """Stream ``run.status`` and ``run.progress`` events of an experiment."""
    await websocket.accept()

    async def forward() -> None:
        async for message in infrastructure.subscriber.subscribe(experiment_id):
            await websocket.send_text(message)

    async def wait_for_disconnect() -> None:
        with contextlib.suppress(WebSocketDisconnect):
            while True:
                await websocket.receive_text()

    tasks = [asyncio.create_task(forward()), asyncio.create_task(wait_for_disconnect())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
