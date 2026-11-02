"""Payloads of the real-time events streamed to the frontend."""

import uuid
from typing import Any

from esphea.experiments.observers import RunProgress
from esphea.persistence.models import RunStatus

FRONT_DECIMALS = 6


def experiment_channel(experiment_id: uuid.UUID) -> str:
    return f"esphea:experiment:{experiment_id}"


def run_status_event(
    experiment_id: uuid.UUID,
    run_id: uuid.UUID,
    status: RunStatus,
    *,
    generation: int | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "run.status",
        "experiment_id": str(experiment_id),
        "run_id": str(run_id),
        "status": status.value,
        "generation": generation,
        "error": error,
    }


def run_progress_event(
    experiment_id: uuid.UUID, run_id: uuid.UUID, progress: RunProgress
) -> dict[str, Any]:
    metrics = progress.metrics
    return {
        "type": "run.progress",
        "experiment_id": str(experiment_id),
        "run_id": str(run_id),
        "generation": progress.generation,
        "n_gen": progress.n_gen,
        "metrics": None
        if metrics is None
        else {
            "generation": metrics.generation,
            "n_nondominated": metrics.n_nondominated,
            "values": metrics.values,
        },
        "front": progress.front.round(FRONT_DECIMALS).tolist(),
    }
