import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.registry import default_problem_registry
from esphea.messaging.ports import JobKind
from esphea.persistence.models import AnalysisRow
from esphea.persistence.repositories import AnalysisRepository
from esphea.services.analyses import group_key, round_up, summarize_runs
from esphea.services.analysis_execution import AnalysisExecutionService
from esphea.services.execution import RunService
from esphea.services.watchdog import AnalysisJobs, RecoveryAction, Watchdog
from esphea.topology.storage import analysis_directory
from tests.integration.conftest import RecordingQueue

N_GEN = 8


@pytest.fixture
def analysis_service(sessions: sessionmaker[Session], runs_dir: Path) -> AnalysisExecutionService:
    return AnalysisExecutionService(
        sessions, problems=default_problem_registry(), runs_dir=runs_dir
    )


@pytest.fixture
def run_id(client: TestClient, queue: RecordingQueue, run_service: RunService) -> str:
    """A completed run with every generation stored."""
    queue.executors[JobKind.RUN] = run_service
    body = {
        "name": "topology",
        "problem": {"name": "dtlz2", "n_obj": 3, "k": 5},
        "algorithm": {"name": "nsga2", "pop_size": 20},
        "n_gen": N_GEN,
        "n_runs": 1,
    }
    experiment = client.post("/api/experiments", json=body).json()
    run: dict[str, Any] = client.get(f"/api/experiments/{experiment['id']}").json()["runs"][0]
    assert run["status"] == "completed"
    return str(run["id"])


def create(client: TestClient, run_id: str, **config: Any) -> dict[str, Any]:
    response = client.post(
        f"/api/runs/{run_id}/analyses", json={"kind": "topology", "max_epsilon": 2.0, **config}
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def test_full_analysis_through_the_api(
    client: TestClient,
    queue: RecordingQueue,
    analysis_service: AnalysisExecutionService,
    run_id: str,
) -> None:
    queue.executors[JobKind.ANALYSIS] = analysis_service
    analysis = create(client, run_id, distance_matrix=True)
    analysis = client.get(f"/api/analyses/{analysis['id']}").json()
    assert analysis["status"] == "completed"
    assert analysis["progress"] == analysis["total"] == 2 * (N_GEN + 1)
    url = f"/api/analyses/{analysis['id']}"

    series = client.get(f"{url}/series").json()
    assert series["generation"] == list(range(N_GEN + 1))
    assert series["hausdorff_previous"][0] is None
    h0 = series["dimensions"][0]
    assert set(h0["distances"]) == {"bottleneck", "wasserstein_1"}
    assert h0["distances"]["bottleneck"]["previous"][0] is None
    assert h0["distances"]["bottleneck"]["final"][-1] == 0.0

    diagram = client.get(f"{url}/diagrams/4").json()
    assert [d["dimension"] for d in diagram["dimensions"]] == [0, 1]
    assert diagram["max_epsilon"] == 2.0

    betti = client.get(f"{url}/betti", params={"dimension": 1, "resolution": 20}).json()
    assert len(betti["epsilon"]) == 20
    assert len(betti["values"]) == N_GEN + 1

    matrix = client.get(f"{url}/matrix", params={"dimension": 0, "metric": "wasserstein_1"}).json()
    assert len(matrix["values"]) == N_GEN + 1

    assert client.get(f"{url}/diagrams/999").status_code == 404
    assert client.get(f"{url}/betti", params={"dimension": 2}).status_code == 404

    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


def test_listing_and_suggestion(client: TestClient, queue: RecordingQueue, run_id: str) -> None:
    created = create(client, run_id, point_cloud="merged", normalization="ideal_nadir")
    assert created["status"] == "queued"
    assert [j.kind for j in queue.enqueued][-1] == JobKind.ANALYSIS
    listed = client.get(f"/api/runs/{run_id}/analyses").json()
    assert [a["id"] for a in listed] == [created["id"]]
    assert client.delete(f"/api/analyses/{created['id']}").status_code == 409  # still queued

    suggestion = client.get(
        f"/api/runs/{run_id}/epsilon-suggestion", params={"normalization": "min_max"}
    ).json()
    assert 0 < suggestion["median_nearest_neighbour"] < suggestion["max_diameter"]
    assert suggestion["max_diameter"] <= suggestion["suggested_max_epsilon"] <= 2.0  # unit box


def test_unfinished_runs_cannot_be_analysed(client: TestClient) -> None:
    body = {"name": "x", "algorithm": {"name": "nsga2", "pop_size": 20}, "n_gen": 5}
    experiment = client.post("/api/experiments", json=body).json()
    run_id = experiment["runs"][0]["id"]
    response = client.post(
        f"/api/runs/{run_id}/analyses", json={"kind": "topology", "max_epsilon": 1.0}
    )
    assert response.status_code == 409
    assert (
        client.post(
            f"/api/runs/{uuid.uuid4()}/analyses", json={"kind": "topology", "max_epsilon": 1.0}
        ).status_code
        == 404
    )


def test_lost_analysis_worker_is_retried(
    client: TestClient,
    sessions: sessionmaker[Session],
    queue: RecordingQueue,
    analysis_service: AnalysisExecutionService,
    runs_dir: Path,
    run_id: str,
) -> None:
    analysis_id = uuid.UUID(create(client, run_id)["id"])
    with sessions.begin() as session:
        assert AnalysisRepository(session).claim(analysis_id, 1)
        session.execute(
            update(AnalysisRow)
            .where(AnalysisRow.id == analysis_id)
            .values(heartbeat_at=datetime.now(UTC) - timedelta(minutes=5))
        )
    stale = analysis_directory(runs_dir, uuid.UUID(run_id), analysis_id, 1)
    stale.mkdir(parents=True)

    queue.executors[JobKind.ANALYSIS] = analysis_service
    watchdog = Watchdog(
        sessions,
        queue=queue,
        jobs=[AnalysisJobs(runs_dir=runs_dir)],
        lease_timeout=timedelta(seconds=60),
        max_attempts=3,
        enqueue_grace=timedelta(seconds=120),
    )
    [recovery] = watchdog.sweep()

    assert (recovery.kind, recovery.action) == (JobKind.ANALYSIS, RecoveryAction.RETRIED)
    assert not stale.exists()
    analysis = client.get(f"/api/analyses/{analysis_id}").json()
    assert (analysis["status"], analysis["attempt"]) == ("completed", 2)
    assert client.get(f"/api/analyses/{analysis_id}/series").status_code == 200


def test_round_up() -> None:
    assert round_up(1.234) == 1.3
    assert round_up(0.04321) == 0.044
    assert round_up(2.0) == 2.0


def test_summarize_runs_aligns_generations_and_ignores_missing_values() -> None:
    runs = [
        ([0, 1, 2], {"x": np.array([np.nan, 1.0, 2.0])}),
        ([0, 1], {"x": np.array([np.nan, 3.0])}),
    ]
    generations, n_runs, series = summarize_runs(runs)
    assert generations == [0, 1, 2]
    assert n_runs == [2, 2, 1]
    assert np.isnan(series["x"].median[0])
    np.testing.assert_allclose(series["x"].median[1:], [2.0, 2.0])
    np.testing.assert_allclose(series["x"].q1[1:], [1.5, 2.0])


def test_group_key_ignores_stored_extras_only() -> None:
    base = {"max_epsilon": 2.0, "point_cloud": "survivors"}
    assert group_key("topology", base) == group_key(
        "topology", {**base, "distance_matrix": True, "max_dimension": 1}
    )
    assert group_key("topology", base) != group_key("topology", {**base, "max_epsilon": 1.0})
    zigzag = {"epsilons": [0.2, 0.1]}
    assert group_key("zigzag", zigzag) == group_key(
        "zigzag", {"epsilons": [0.1, 0.2], "representatives": 3}
    )
    assert group_key("zigzag", zigzag) != group_key("topology", {"max_epsilon": 0.2})


def test_analysis_groups_across_runs(
    client: TestClient,
    queue: RecordingQueue,
    run_service: RunService,
    analysis_service: AnalysisExecutionService,
) -> None:
    queue.executors[JobKind.RUN] = run_service
    queue.executors[JobKind.ANALYSIS] = analysis_service
    body = {
        "name": "groups",
        "problem": {"name": "zdt1", "n_var": 6},
        "algorithm": {"name": "nsga2", "pop_size": 12},
        "n_gen": N_GEN,
        "n_runs": 2,
    }
    experiment = client.post("/api/experiments", json=body).json()
    runs = client.get(f"/api/experiments/{experiment['id']}").json()["runs"]
    # one analysis per run, created separately; the second also stores a matrix
    create(client, runs[0]["id"], max_epsilon=1.0)
    create(client, runs[1]["id"], max_epsilon=1.0, distance_matrix=True)
    create(client, runs[0]["id"], max_epsilon=0.5)
    url = f"/api/experiments/{experiment['id']}/analysis-groups"

    groups = client.get(url).json()
    assert [(g["config"]["max_epsilon"], g["runs"], g["pending"]) for g in groups] == [
        (0.5, 1, 0),
        (1.0, 2, 0),
    ]
    key = groups[1]["key"]

    summary = client.get(f"{url}/{key}/summary", params={"dimension": 0}).json()
    assert summary["kind"] == "topology"
    assert summary["generation"] == list(range(N_GEN + 1))
    assert summary["n_runs"] == [2] * (N_GEN + 1)
    assert summary["totals"] == {}
    assert {"n_bars", "total_persistence", "persistent_entropy", "bottleneck_final"} <= set(
        summary["series"]
    )
    assert summary["series"]["bottleneck_previous"]["median"][0] is None
    assert summary["series"]["bottleneck_final"]["median"][-1] == 0.0

    assert client.get(f"{url}/{key}/summary", params={"dimension": 2}).status_code == 404
    assert client.get(f"{url}/unknown/summary").status_code == 404
