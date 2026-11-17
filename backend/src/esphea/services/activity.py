"""What the platform is doing: jobs in progress, the job queue, workers and failures.

The database is the source of truth for jobs; the queue tells which worker holds
each running job and where each waiting job stands. Both views can disagree for a
moment (a job just claimed, a queue lost with Redis), which is what the watchdog
repairs and what this view makes visible.
"""

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy.orm import Session

from esphea.messaging.ports import (
    ActivityMonitor,
    JobKind,
    JobRef,
    QueueState,
    WatchdogState,
    WorkerState,
)
from esphea.persistence.models import AnalysisRow, LeasedJob, RunRow, RunStatus
from esphea.persistence.repositories import (
    AnalysisRepository,
    LeasedJobRepository,
    RunRepository,
)
from esphea.topology.config import AnalysisConfig, parse_analysis_config

logger = logging.getLogger(__name__)

RECENT_FAILURES = 20
FINISHED_WINDOW = timedelta(hours=24)
LATE_AFTER_BEATS = 3
"""A lease is late once this many heartbeats were missed (the worker may be overloaded)."""

type JobKey = tuple[JobKind, uuid.UUID]


class LeaseHealth(StrEnum):
    HEALTHY = "healthy"
    LATE = "late"
    EXPIRED = "expired"  # the watchdog will hand the job to another worker


class WorkerJobStatus(StrEnum):
    """How the job a worker holds stands in the database."""

    RUNNING = "running"  # the worker executes the job's current attempt
    CLAIMING = "claiming"  # the worker is taking the job from the queue
    ENDED = "ended"  # the job is over (or deleted): the worker is wrapping up
    SUPERSEDED = "superseded"  # the job went to a new attempt: the worker was presumed lost


@dataclass(frozen=True, slots=True)
class ActivityLimits:
    """Settings that give the timestamps of the jobs their meaning."""

    heartbeat_interval: timedelta
    lease_timeout: timedelta
    max_attempts: int
    enqueue_grace: timedelta


@dataclass(frozen=True, slots=True)
class Subject:
    """What a job works on: a run, or an analysis of a run."""

    experiment_id: uuid.UUID
    experiment_name: str
    run_id: uuid.UUID
    run_index: int
    analysis: AnalysisConfig | None = None
    batch_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class RunningJob:
    kind: JobKind
    id: uuid.UUID
    subject: Subject
    attempt: int
    done: int  # generations, or steps of the analysis
    total: int  # 0 while an analysis has not counted its steps yet
    started_at: datetime | None
    heartbeat_at: datetime | None
    lease: LeaseHealth
    worker: str | None  # None: no worker reports holding it


@dataclass(frozen=True, slots=True)
class WorkerActivity:
    state: WorkerState
    job_status: WorkerJobStatus | None  # None: the worker holds no job
    subject: Subject | None  # what its job works on (None if deleted)


@dataclass(frozen=True, slots=True)
class WaitingGroup:
    """Queued jobs of one experiment (runs) or one batch of analyses."""

    kind: JobKind
    experiment_id: uuid.UUID
    experiment_name: str
    analysis: AnalysisConfig | None
    batch_id: uuid.UUID | None
    run_indices: tuple[int, ...]
    retries: int  # jobs queued again after their worker was lost
    next_position: int | None  # 1 = next job a worker takes; 0 = being taken now
    missing: int | None  # not in the queue (None when the queue is unreachable)
    enqueued_at: datetime | None  # the oldest


@dataclass(frozen=True, slots=True)
class FailedJob:
    kind: JobKind
    id: uuid.UUID
    subject: Subject
    attempt: int
    finished_at: datetime | None
    error: str | None


@dataclass(frozen=True, slots=True)
class Activity:
    at: datetime
    limits: ActivityLimits
    queue: QueueState | None  # None: the queue could not be read
    queue_error: str | None
    workers: list[WorkerActivity]
    watchdog: WatchdogState | None
    recovered: dict[JobKey, Subject]  # subjects of the recoveries
    running: list[RunningJob]
    waiting: list[WaitingGroup]
    failures: list[FailedJob]
    finished: dict[JobKind, dict[RunStatus, int]]  # in the last FINISHED_WINDOW


def _aware(moment: datetime | None) -> datetime | None:
    """Timestamps are stored in UTC; some backends (SQLite) drop the zone."""
    if moment is None or moment.tzinfo is not None:
        return moment
    return moment.replace(tzinfo=UTC)


def _subject(job: LeasedJob) -> Subject:
    if isinstance(job, RunRow):
        return Subject(job.experiment_id, job.experiment.name, job.id, job.index)
    assert isinstance(job, AnalysisRow)
    run = job.run
    return Subject(
        run.experiment_id,
        run.experiment.name,
        run.id,
        run.index,
        analysis=parse_analysis_config(job.kind, job.config),
        batch_id=job.batch_id,
    )


def _job_status(ref: JobRef, job: LeasedJob) -> WorkerJobStatus:
    if job.status == RunStatus.RUNNING and job.attempt == ref.attempt:
        return WorkerJobStatus.RUNNING
    if job.status == RunStatus.QUEUED and job.attempt == ref.attempt - 1:
        return WorkerJobStatus.CLAIMING
    if not job.status.is_active:
        return WorkerJobStatus.ENDED
    return WorkerJobStatus.SUPERSEDED


def _run_index(job: LeasedJob) -> int:
    if isinstance(job, RunRow):
        return job.index
    assert isinstance(job, AnalysisRow)
    return job.run.index


def _progress(job: LeasedJob) -> tuple[int, int]:
    if isinstance(job, RunRow):
        return job.generation, int(job.experiment.config["n_gen"])
    assert isinstance(job, AnalysisRow)
    return job.progress, job.total


class ActivityService:
    def __init__(
        self,
        session: Session,
        *,
        monitor: ActivityMonitor,
        limits: ActivityLimits,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repositories: dict[JobKind, LeasedJobRepository[Any]] = {
            JobKind.RUN: RunRepository(session),
            JobKind.ANALYSIS: AnalysisRepository(session),
        }
        self._monitor = monitor
        self._limits = limits
        self._clock = clock

    def snapshot(self) -> Activity:
        now = self._clock()
        queue, queue_error = self._queue()
        holders = {} if queue is None else {w.job: w.name for w in queue.workers if w.job}
        active = [
            (kind, job)
            for kind, repository in self._repositories.items()
            for job in repository.list_active()
        ]
        running = [
            self._running(kind, job, now, holders)
            for kind, job in active
            if job.status == RunStatus.RUNNING
        ]
        running.sort(key=lambda job: job.started_at or now)
        active_by_key: dict[JobKey, LeasedJob] = {(kind, job.id): job for kind, job in active}
        failures = sorted(
            (
                FailedJob(
                    kind,
                    job.id,
                    _subject(job),
                    job.attempt,
                    _aware(job.finished_at),
                    job.error,
                )
                for kind, repository in self._repositories.items()
                for job in repository.list_failed(RECENT_FAILURES)
            ),
            key=lambda job: job.finished_at or now,
            reverse=True,
        )[:RECENT_FAILURES]
        watchdog = self._watchdog() if queue is not None else None
        return Activity(
            at=now,
            limits=self._limits,
            queue=queue,
            queue_error=queue_error,
            workers=self._workers(queue, active_by_key),
            watchdog=watchdog,
            recovered=self._recovered(watchdog),
            running=running,
            waiting=self._waiting(
                [(kind, job) for kind, job in active if job.status == RunStatus.QUEUED], queue
            ),
            failures=failures,
            finished={
                kind: repository.count_finished_since(now - FINISHED_WINDOW)
                for kind, repository in self._repositories.items()
            },
        )

    def _queue(self) -> tuple[QueueState | None, str | None]:
        try:
            return self._monitor.queue(), None
        except Exception as exc:  # the page still shows what the database knows
            logger.warning("could not read the job queue", exc_info=True)
            return None, f"{type(exc).__name__}: {exc}"

    def _watchdog(self) -> WatchdogState | None:
        try:
            return self._monitor.watchdog()
        except Exception:
            logger.warning("could not read the watchdog's report", exc_info=True)
            return None

    def _jobs(self, keys: Sequence[JobKey]) -> dict[JobKey, LeasedJob]:
        """Jobs by kind and id (deleted ones are left out)."""
        found: dict[JobKey, LeasedJob] = {}
        for kind, repository in self._repositories.items():
            ids = list({entity_id for job_kind, entity_id in keys if job_kind == kind})
            if ids:
                found.update({(kind, job.id): job for job in repository.list_by_ids(ids)})
        return found

    def _recovered(self, watchdog: WatchdogState | None) -> dict[JobKey, Subject]:
        """What the recovered jobs work on (jobs deleted since are left out)."""
        if watchdog is None:
            return {}
        jobs = self._jobs([(r.job.kind, r.job.entity_id) for r in watchdog.recoveries])
        return {key: _subject(job) for key, job in jobs.items()}

    def _workers(
        self, queue: QueueState | None, active: Mapping[JobKey, LeasedJob]
    ) -> list[WorkerActivity]:
        """Workers, with the job they hold checked against the database.

        The queue forgets a worker only once its heartbeat expires (about 90 s for
        a busy one), so a worker that died keeps "holding" its job for a while.
        """
        if queue is None:
            return []
        held = [(w.job.kind, w.job.entity_id) for w in queue.workers if w.job is not None]
        jobs = {**self._jobs([key for key in held if key not in active]), **active}
        workers = []
        for worker in queue.workers:
            ref = worker.job
            job = None if ref is None else jobs.get((ref.kind, ref.entity_id))
            if ref is None:
                status = None
            elif job is None:
                status = WorkerJobStatus.ENDED
            else:
                status = _job_status(ref, job)
            subject = None if job is None else _subject(job)
            workers.append(WorkerActivity(worker, status, subject))
        return workers

    def _lease(self, job: LeasedJob, now: datetime) -> LeaseHealth:
        beat = _aware(job.heartbeat_at or job.started_at)
        age = now - beat if beat is not None else self._limits.lease_timeout * 2
        if age > self._limits.lease_timeout:
            return LeaseHealth.EXPIRED
        if age > self._limits.heartbeat_interval * LATE_AFTER_BEATS:
            return LeaseHealth.LATE
        return LeaseHealth.HEALTHY

    def _running(
        self, kind: JobKind, job: LeasedJob, now: datetime, holders: dict[JobRef, str]
    ) -> RunningJob:
        done, total = _progress(job)
        return RunningJob(
            kind=kind,
            id=job.id,
            subject=_subject(job),
            attempt=job.attempt,
            done=done,
            total=total,
            started_at=_aware(job.started_at),
            heartbeat_at=_aware(job.heartbeat_at),
            lease=self._lease(job, now),
            worker=holders.get(JobRef(kind, job.id, job.attempt)),
        )

    @staticmethod
    def _waiting(
        queued: Sequence[tuple[JobKind, LeasedJob]], queue: QueueState | None
    ) -> list[WaitingGroup]:
        positions = {} if queue is None else {ref: i + 1 for i, ref in enumerate(queue.waiting)}
        taken = set() if queue is None else {w.job for w in queue.workers if w.job}
        groups: dict[JobKey, list[tuple[LeasedJob, int | None]]] = {}
        for kind, job in queued:
            ref = JobRef(kind, job.id, job.attempt + 1)  # the attempt it waits for
            position = 0 if ref in taken else positions.get(ref)
            batch = job.batch_id if isinstance(job, AnalysisRow) else None
            key = (kind, job.experiment_id if isinstance(job, RunRow) else batch or job.id)
            groups.setdefault(key, []).append((job, position))
        result = []
        for (kind, _), members in groups.items():
            first = _subject(members[0][0])
            known = [position for _, position in members if position is not None]
            enqueued = [_aware(job.enqueued_at) for job, _ in members if job.enqueued_at]
            result.append(
                WaitingGroup(
                    kind=kind,
                    experiment_id=first.experiment_id,
                    experiment_name=first.experiment_name,
                    analysis=first.analysis,
                    batch_id=first.batch_id,
                    run_indices=tuple(sorted(_run_index(job) for job, _ in members)),
                    retries=sum(job.attempt > 0 for job, _ in members),
                    next_position=min(known) if known else None,
                    missing=None if queue is None else len(members) - len(known),
                    enqueued_at=min((m for m in enqueued if m is not None), default=None),
                )
            )
        result.sort(
            key=lambda group: (
                group.next_position is None,
                group.next_position or 0,
                group.enqueued_at or datetime.max.replace(tzinfo=UTC),
            )
        )
        return result
