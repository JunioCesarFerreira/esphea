"""Response models of the activity view: workers, job queue, jobs in progress."""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from esphea.messaging.ports import (
    JobKind,
    JobRef,
    QueueState,
    RecoveryRecord,
    WatchdogState,
)
from esphea.persistence.models import RunStatus
from esphea.services.activity import (
    Activity,
    ActivityLimits,
    FailedJob,
    LeaseHealth,
    RunningJob,
    Subject,
    WaitingGroup,
    WorkerActivity,
    WorkerJobStatus,
)
from esphea.topology.config import AnalysisConfig


class JobRefOut(BaseModel):
    kind: JobKind
    id: uuid.UUID
    attempt: int

    @classmethod
    def from_ref(cls, ref: JobRef) -> Self:
        return cls(kind=ref.kind, id=ref.entity_id, attempt=ref.attempt)


class QueueOut(BaseModel):
    """Job counts of the queue and of its registries."""

    name: str
    waiting: int = Field(description="Jobs waiting for a worker.")
    started: int
    failed: int = Field(description="Jobs that crashed their worker process (kept a week).")
    finished: int = Field(description="Jobs finished in the last hour.")
    deferred: int
    scheduled: int

    @classmethod
    def from_state(cls, queue: QueueState) -> Self:
        return cls(
            name=queue.name,
            waiting=len(queue.waiting),
            started=queue.started,
            failed=queue.failed,
            finished=queue.finished,
            deferred=queue.deferred,
            scheduled=queue.scheduled,
        )


class SubjectOut(BaseModel):
    experiment_id: uuid.UUID
    experiment_name: str
    run_id: uuid.UUID
    run_index: int
    analysis: AnalysisConfig | None = Field(description="Null for a run.")
    batch_id: uuid.UUID | None

    @classmethod
    def from_subject(cls, subject: Subject) -> Self:
        return cls(
            experiment_id=subject.experiment_id,
            experiment_name=subject.experiment_name,
            run_id=subject.run_id,
            run_index=subject.run_index,
            analysis=subject.analysis,
            batch_id=subject.batch_id,
        )


class WorkerOut(BaseModel):
    name: str
    state: str = Field(description="busy, idle, suspended, ... or unknown")
    hostname: str | None
    pid: int | None
    job: JobRefOut | None = Field(description="The job it is executing.")
    job_status: WorkerJobStatus | None = Field(
        description="How that job stands in the database (null without a job)."
    )
    subject: SubjectOut | None = Field(description="What that job works on.")
    born_at: datetime | None
    seen_at: datetime | None = Field(description="Last heartbeat sent to the queue.")
    successful_jobs: int
    failed_jobs: int
    working_seconds: float

    @classmethod
    def from_activity(cls, activity: WorkerActivity) -> Self:
        worker = activity.state
        return cls(
            name=worker.name,
            state=worker.state,
            hostname=worker.hostname,
            pid=worker.pid,
            job=None if worker.job is None else JobRefOut.from_ref(worker.job),
            job_status=activity.job_status,
            subject=None if activity.subject is None else SubjectOut.from_subject(activity.subject),
            born_at=worker.born_at,
            seen_at=worker.seen_at,
            successful_jobs=worker.successful_jobs,
            failed_jobs=worker.failed_jobs,
            working_seconds=worker.working_seconds,
        )


class RecoveryOut(BaseModel):
    at: datetime
    job: JobRefOut
    action: str = Field(description="retried, failed or reenqueued")
    subject: SubjectOut | None = Field(description="Null if the job was deleted since.")

    @classmethod
    def from_record(cls, record: RecoveryRecord, subject: Subject | None) -> Self:
        return cls(
            at=record.at,
            job=JobRefOut.from_ref(record.job),
            action=record.action,
            subject=None if subject is None else SubjectOut.from_subject(subject),
        )


class WatchdogOut(BaseModel):
    swept_at: datetime
    interval_seconds: float
    recoveries: list[RecoveryOut] = Field(description="The last 50, most recent first.")

    @classmethod
    def from_state(
        cls, watchdog: WatchdogState, subjects: Mapping[tuple[JobKind, uuid.UUID], Subject]
    ) -> Self:
        return cls(
            swept_at=watchdog.swept_at,
            interval_seconds=watchdog.interval_seconds,
            recoveries=[
                RecoveryOut.from_record(r, subjects.get((r.job.kind, r.job.entity_id)))
                for r in watchdog.recoveries
            ],
        )


class RunningJobOut(BaseModel):
    kind: JobKind
    id: uuid.UUID
    subject: SubjectOut
    attempt: int
    done: int = Field(description="Generations of a run, steps of an analysis.")
    total: int = Field(description="0 while an analysis has not counted its steps yet.")
    started_at: datetime | None
    heartbeat_at: datetime | None
    lease: LeaseHealth
    worker: str | None = Field(description="Null when no worker reports holding the job.")

    @classmethod
    def from_job(cls, job: RunningJob) -> Self:
        return cls(
            kind=job.kind,
            id=job.id,
            subject=SubjectOut.from_subject(job.subject),
            attempt=job.attempt,
            done=job.done,
            total=job.total,
            started_at=job.started_at,
            heartbeat_at=job.heartbeat_at,
            lease=job.lease,
            worker=job.worker,
        )


class WaitingGroupOut(BaseModel):
    """Queued jobs of one experiment (runs) or of one batch of analyses."""

    kind: JobKind
    experiment_id: uuid.UUID
    experiment_name: str
    analysis: AnalysisConfig | None
    batch_id: uuid.UUID | None
    run_indices: list[int]
    retries: int = Field(description="Jobs queued again after their worker was lost.")
    next_position: int | None = Field(
        description="1 = the next job a worker takes; 0 = being taken now; null = not queued."
    )
    missing: int | None = Field(
        description="Jobs absent from the queue (the watchdog enqueues them again)."
    )
    enqueued_at: datetime | None = Field(description="The oldest of the group.")

    @classmethod
    def from_group(cls, group: WaitingGroup) -> Self:
        return cls(
            kind=group.kind,
            experiment_id=group.experiment_id,
            experiment_name=group.experiment_name,
            analysis=group.analysis,
            batch_id=group.batch_id,
            run_indices=list(group.run_indices),
            retries=group.retries,
            next_position=group.next_position,
            missing=group.missing,
            enqueued_at=group.enqueued_at,
        )


class FailedJobOut(BaseModel):
    kind: JobKind
    id: uuid.UUID
    subject: SubjectOut
    attempt: int
    finished_at: datetime | None
    error: str | None

    @classmethod
    def from_job(cls, job: FailedJob) -> Self:
        return cls(
            kind=job.kind,
            id=job.id,
            subject=SubjectOut.from_subject(job.subject),
            attempt=job.attempt,
            finished_at=job.finished_at,
            error=job.error,
        )


class LimitsOut(BaseModel):
    heartbeat_interval_seconds: float
    lease_timeout_seconds: float
    max_attempts: int
    enqueue_grace_seconds: float

    @classmethod
    def from_limits(cls, limits: ActivityLimits) -> Self:
        return cls(
            heartbeat_interval_seconds=limits.heartbeat_interval.total_seconds(),
            lease_timeout_seconds=limits.lease_timeout.total_seconds(),
            max_attempts=limits.max_attempts,
            enqueue_grace_seconds=limits.enqueue_grace.total_seconds(),
        )


class FinishedOut(BaseModel):
    kind: JobKind
    completed: int
    failed: int
    cancelled: int


class ActivityOut(BaseModel):
    at: datetime = Field(description="Server time of the snapshot (ages are relative to it).")
    limits: LimitsOut
    queue: QueueOut | None = Field(description="Null when the queue could not be read.")
    queue_error: str | None
    workers: list[WorkerOut]
    watchdog: WatchdogOut | None = Field(description="Null if it never reported a sweep.")
    running: list[RunningJobOut]
    waiting: list[WaitingGroupOut]
    failures: list[FailedJobOut] = Field(description="The most recent failures.")
    finished: list[FinishedOut] = Field(description="Jobs that ended in the last 24 hours.")

    @classmethod
    def from_activity(cls, activity: Activity) -> Self:
        queue = activity.queue
        return cls(
            at=activity.at,
            limits=LimitsOut.from_limits(activity.limits),
            queue=None if queue is None else QueueOut.from_state(queue),
            queue_error=activity.queue_error,
            workers=[WorkerOut.from_activity(worker) for worker in activity.workers],
            watchdog=None
            if activity.watchdog is None
            else WatchdogOut.from_state(activity.watchdog, activity.recovered),
            running=[RunningJobOut.from_job(job) for job in activity.running],
            waiting=[WaitingGroupOut.from_group(group) for group in activity.waiting],
            failures=[FailedJobOut.from_job(job) for job in activity.failures],
            finished=[
                FinishedOut(
                    kind=kind,
                    completed=counts.get(RunStatus.COMPLETED, 0),
                    failed=counts.get(RunStatus.FAILED, 0),
                    cancelled=counts.get(RunStatus.CANCELLED, 0),
                )
                for kind, counts in activity.finished.items()
            ],
        )
