"""Run endpoints: metric series and generation snapshots."""

import csv
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from esphea.api.dependencies import ResultsServiceDep
from esphea.api.schemas import GenerationSnapshotOut, MetricSeriesOut, StoredGenerationsOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}/metrics")
def get_run_metrics(run_id: uuid.UUID, service: ResultsServiceDep) -> MetricSeriesOut:
    return MetricSeriesOut.from_series(service.run_metrics(run_id))


@router.get("/{run_id}/metrics.csv", response_class=Response)
def export_run_metrics(run_id: uuid.UUID, service: ResultsServiceDep) -> Response:
    series = service.run_metrics(run_id)
    names = sorted(series.values)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["generation", "n_nondominated", "elapsed_seconds", *names])
    for i, generation in enumerate(series.generation):
        writer.writerow(
            [
                generation,
                series.n_nondominated[i],
                series.elapsed_seconds[i],
                *(series.values[name][i] for name in names),
            ]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="run-{run_id}-metrics.csv"'},
    )


@router.get("/{run_id}/generations")
def list_stored_generations(run_id: uuid.UUID, service: ResultsServiceDep) -> StoredGenerationsOut:
    return StoredGenerationsOut(generations=service.stored_generations(run_id))


@router.get("/{run_id}/generations/{generation}")
def get_generation(
    run_id: uuid.UUID,
    generation: int,
    service: ResultsServiceDep,
    decision_variables: Annotated[bool, Query()] = False,
) -> GenerationSnapshotOut:
    """Parent pool, offspring (with lineage) and survival outcome of a stored generation."""
    snapshot = service.snapshot(run_id, generation, decision_variables=decision_variables)
    return GenerationSnapshotOut.from_snapshot(run_id, snapshot)
