"""Observability of the workers, the job queue and the jobs in progress."""

from fastapi import APIRouter

from esphea.api.activity_schemas import ActivityOut
from esphea.api.dependencies import ActivityServiceDep

router = APIRouter(tags=["activity"])


@router.get("/activity")
def get_activity(service: ActivityServiceDep) -> ActivityOut:
    """Workers, job queue, jobs in progress or waiting, recent failures and the watchdog."""
    return ActivityOut.from_activity(service.snapshot())
