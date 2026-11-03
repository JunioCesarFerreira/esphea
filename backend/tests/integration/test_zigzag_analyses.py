from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from esphea.experiments.registry import default_problem_registry
from esphea.messaging.ports import JobKind
from esphea.services.analysis_execution import AnalysisExecutionService
from esphea.services.execution import RunService
from tests.integration.conftest import RecordingQueue

N_GEN = 6
ZIGZAG = {"kind": "zigzag", "epsilons": [0.3, 0.15], "max_dimension": 1, "representatives": 5}


@pytest.fixture
def experiment(
    client: TestClient,
    queue: RecordingQueue,
    run_service: RunService,
    sessions: sessionmaker[Session],
    runs_dir: Path,
) -> dict[str, Any]:
    """A completed two-run experiment; analyses execute inline when enqueued."""
    queue.executors[JobKind.RUN] = run_service
    queue.executors[JobKind.ANALYSIS] = AnalysisExecutionService(
        sessions, problems=default_problem_registry(), runs_dir=runs_dir
    )
    body = {
        "name": "zigzag",
        "problem": {"name": "dtlz2", "n_obj": 3, "k": 5},
        "algorithm": {"name": "nsga2", "pop_size": 20},
        "n_gen": N_GEN,
        "n_runs": 2,
    }
    created = client.post("/api/experiments", json=body).json()
    return dict(client.get(f"/api/experiments/{created['id']}").json())


def test_zigzag_of_a_run(client: TestClient, experiment: dict[str, Any]) -> None:
    run_id = experiment["runs"][0]["id"]
    analysis = client.post(f"/api/runs/{run_id}/analyses", json=ZIGZAG).json()
    assert analysis["config"]["epsilons"] == [0.15, 0.3]  # sorted
    url = f"/api/analyses/{analysis['id']}"
    assert client.get(url).json()["status"] == "completed"

    bars = client.get(f"{url}/zigzag/bars", params={"epsilon_index": 1, "dimension": 0}).json()
    assert bars["epsilon"] == 0.3
    assert bars["n_steps"] == 2 * N_GEN + 1
    assert all(
        0 <= b < d <= bars["n_steps"] for b, d in zip(bars["birth"], bars["death"], strict=True)
    )
    long_only = client.get(
        f"{url}/zigzag/bars", params={"epsilon_index": 1, "min_lifetime": 3}
    ).json()
    assert len(long_only["bar"]) <= len(bars["bar"])

    events = client.get(f"{url}/zigzag/events", params={"epsilon_index": 1}).json()
    assert len(events["betti_p"]) == N_GEN + 1
    assert events["betti_r"][0] is None
    # Betti numbers change exactly by the births and deaths in between
    for t in range(1, N_GEN + 1):
        assert events["betti_r"][t] == (
            events["betti_p"][t - 1] + events["births_variation"][t] - events["deaths_variation"][t]
        )
        assert events["betti_p"][t] == (
            events["betti_r"][t] + events["births_selection"][t] - events["deaths_selection"][t]
        )

    index = next(i for i, r in enumerate(bars["representative"]) if r)
    bar, birth = bars["bar"][index], bars["birth"][index]
    view = client.get(
        f"{url}/zigzag/representative", params={"epsilon_index": 1, "bar": bar, "step": birth}
    ).json()
    assert view["dimension"] == 0
    assert len(view["points"]) == len(view["members"])
    vertices = {v for simplex in view["simplices"] for v in simplex}
    assert vertices <= set(view["component"]) <= set(view["members"])

    outside = client.get(
        f"{url}/zigzag/representative",
        params={"epsilon_index": 1, "bar": bar, "step": bars["death"][index]},
    )
    assert outside.status_code in (404, 422)
    assert client.get(f"{url}/series").status_code == 409  # not a topology analysis


def test_batch_over_every_run(client: TestClient, experiment: dict[str, Any]) -> None:
    created = client.post(f"/api/experiments/{experiment['id']}/analyses", json=ZIGZAG).json()
    assert len(created) == 2
    batch_ids = {a["batch_id"] for a in created}
    assert len(batch_ids) == 1
    listed = client.get(f"/api/experiments/{experiment['id']}/analyses").json()
    assert {a["id"] for a in listed} == {a["id"] for a in created}

    summary = client.get(
        f"/api/analysis-batches/{batch_ids.pop()}/zigzag-summary",
        params={"epsilon_index": 0, "dimension": 1},
    ).json()
    assert summary["n_runs"] == 2
    assert summary["generation"] == list(range(N_GEN + 1))
    assert set(summary["series"]) == {
        "betti",
        "births_variation",
        "births_selection",
        "deaths_variation",
        "deaths_selection",
    }
    for quartiles in summary["series"].values():
        assert all(
            lo <= mid <= hi
            for lo, mid, hi in zip(
                quartiles["q1"], quartiles["median"], quartiles["q3"], strict=True
            )
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"normalization": "min_max"}, "inclusions"),
        ({"epsilons": [0.1, 0.1]}, "distinct"),
        ({"epsilons": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}, "at most 5"),
    ],
)
def test_invalid_zigzag_configurations(
    client: TestClient, experiment: dict[str, Any], overrides: dict[str, Any], message: str
) -> None:
    run_id = experiment["runs"][0]["id"]
    response = client.post(f"/api/runs/{run_id}/analyses", json={**ZIGZAG, **overrides})
    assert response.status_code == 422
    assert message in response.text


def test_sparse_snapshots_cannot_be_zigzagged(
    client: TestClient, queue: RecordingQueue, run_service: RunService
) -> None:
    queue.executors[JobKind.RUN] = run_service
    body = {
        "name": "sparse",
        "algorithm": {"name": "nsga2", "pop_size": 12},
        "n_gen": 4,
        "snapshots": {"every": 2},
    }
    experiment = client.post("/api/experiments", json=body).json()
    run_id = experiment["runs"][0]["id"]
    response = client.post(f"/api/runs/{run_id}/analyses", json=ZIGZAG)
    assert response.status_code == 422
    assert "every generation" in response.text


def test_suggested_scales(client: TestClient, experiment: dict[str, Any]) -> None:
    run_id = experiment["runs"][0]["id"]
    suggestion = client.get(
        f"/api/runs/{run_id}/epsilon-suggestion", params={"point_cloud": "merged"}
    ).json()
    scales = suggestion["suggested_scales"]
    assert scales == sorted(scales)
    assert scales[0] >= suggestion["median_nearest_neighbour"]
