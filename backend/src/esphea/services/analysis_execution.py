"""Worker-side use case: execute one attempt of a run analysis."""

import logging
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.config import ExperimentConfig
from esphea.experiments.registry import ProblemRegistry
from esphea.experiments.storage import SnapshotReader, snapshot_directory
from esphea.persistence.models import RunStatus
from esphea.persistence.repositories import AnalysisRepository
from esphea.services.leases import Lease, database_renewal
from esphea.topology.analysis import AnalysisInterruptedError, TopologyAnalyzer
from esphea.topology.clouds import build_normalizer
from esphea.topology.config import TopologyAnalysisConfig
from esphea.topology.distances import BottleneckDistance, WassersteinDistance
from esphea.topology.persistence import VietorisRips
from esphea.topology.storage import TopologyResultWriter, analysis_directory

logger = logging.getLogger(__name__)

MAX_ERROR_LENGTH = 4000


class _ProgressRecorder:
    """Writes progress at most every ``interval`` seconds (fenced by attempt)."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        analysis_id: uuid.UUID,
        attempt: int,
        interval: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._sessions = sessions
        self._analysis_id = analysis_id
        self._attempt = attempt
        self._interval = interval
        self._clock = clock
        self._last = -float("inf")

    def __call__(self, done: int, total: int) -> None:
        now = self._clock()
        if done < total and now - self._last < self._interval:
            return
        self._last = now
        with self._sessions.begin() as session:
            AnalysisRepository(session).set_progress(self._analysis_id, self._attempt, done, total)


class AnalysisExecutionService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        problems: ProblemRegistry,
        runs_dir: Path,
        heartbeat_interval: float = 5.0,
        self_fence_after: float = 30.0,
    ) -> None:
        self._sessions = sessions
        self._problems = problems
        self._runs_dir = runs_dir
        self._heartbeat_interval = heartbeat_interval
        self._self_fence_after = self_fence_after

    def execute(self, analysis_id: uuid.UUID, attempt: int) -> RunStatus | None:
        """Compute ``attempt`` of an analysis; None if skipped or the lease was lost."""
        with self._sessions.begin() as session:
            analyses = AnalysisRepository(session)
            analysis = analyses.get(analysis_id)
            if analysis is None or not analyses.claim(analysis_id, attempt):
                logger.info("analysis %s attempt %d is not claimable", analysis_id, attempt)
                return None
            run = analysis.run
            config = TopologyAnalysisConfig.model_validate(analysis.config)
            experiment = ExperimentConfig.model_validate(run.experiment.config)
            snapshots = snapshot_directory(self._runs_dir, run.id, run.attempt)
            output = analysis_directory(self._runs_dir, run.id, analysis_id, attempt)

        lease = Lease(
            database_renewal(self._sessions, AnalysisRepository, analysis_id, attempt),
            name=f"analysis {analysis_id}",
            interval=self._heartbeat_interval,
            self_fence_after=self._self_fence_after,
        )
        lease.start()
        try:
            analyzer = TopologyAnalyzer(
                config,
                computer=VietorisRips(),
                distances=[BottleneckDistance(), WassersteinDistance(1)],
                normalizer=build_normalizer(
                    config.normalization, self._problems.build(experiment.problem)
                ),
            )
            writer = TopologyResultWriter(
                output,
                max_dimension=config.max_dimension,
                max_epsilon=config.max_epsilon,
                metrics=analyzer.metric_names,
            )
            analyzer.analyze(
                SnapshotReader(snapshots),
                writer,
                progress=_ProgressRecorder(self._sessions, analysis_id, attempt),
                should_stop=lambda: lease.lost,
            )
        except Exception as exc:
            if lease.lost or isinstance(exc, AnalysisInterruptedError):
                logger.warning("analysis %s attempt %d lost its lease", analysis_id, attempt)
                shutil.rmtree(output, ignore_errors=True)
                return None
            logger.exception("analysis %s failed", analysis_id)
            error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH]
            return self._finish(analysis_id, attempt, RunStatus.FAILED, output, error=error)
        finally:
            lease.stop()
        return self._finish(analysis_id, attempt, RunStatus.COMPLETED, output)

    def _finish(
        self,
        analysis_id: uuid.UUID,
        attempt: int,
        status: RunStatus,
        output: Path,
        *,
        error: str | None = None,
    ) -> RunStatus | None:
        with self._sessions.begin() as session:
            owned = AnalysisRepository(session).finish(analysis_id, attempt, status, error=error)
        if not owned:
            logger.warning(
                "analysis %s attempt %d finished after losing its lease", analysis_id, attempt
            )
            shutil.rmtree(output, ignore_errors=True)
            return None
        return status
