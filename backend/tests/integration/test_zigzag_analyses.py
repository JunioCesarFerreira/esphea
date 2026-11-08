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
    assert bars["n_simplices"] > 0
    assert bars["representatives_skipped"] is None
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


def test_zigzag_group_summary(client: TestClient, experiment: dict[str, Any]) -> None:
    url = f"/api/experiments/{experiment['id']}"
    client.post(f"{url}/analyses", json=ZIGZAG)
    # the same scales on one run, keeping fewer representatives: same group
    run_id = experiment["runs"][0]["id"]
    client.post(f"/api/runs/{run_id}/analyses", json={**ZIGZAG, "representatives": 0})

    groups = client.get(f"{url}/analysis-groups").json()
    assert len(groups) == 1
    assert groups[0]["kind"] == "zigzag"
    assert groups[0]["runs"] == 2

    summary = client.get(
        f"{url}/analysis-groups/{groups[0]['key']}/summary",
        params={"epsilon_index": 1, "dimension": 0},
    ).json()
    assert summary["generation"] == list(range(N_GEN + 1))
    assert summary["n_runs"] == [2] * (N_GEN + 1)
    assert {"betti", "births", "deaths"} <= set(summary["series"])
    totals = summary["totals"]
    assert set(totals) == {
        "births",
        "births_variation",
        "births_selection",
        "deaths",
        "deaths_variation",
        "deaths_selection",
    }
    for name in ("births", "deaths"):
        spread = totals[name]
        assert spread["q1"] <= spread["median"] <= spread["q3"]
        assert spread["median"] > 0


def test_niche_trackers_beside_the_zigzag(
    client: TestClient, experiment: dict[str, Any], runs_dir: Path
) -> None:
    created = client.post(f"/api/experiments/{experiment['id']}/analyses", json=ZIGZAG).json()
    url = f"/api/analyses/{created[0]['id']}/zigzag"

    comparison = client.get(f"{url}/trackers/comparison", params={"long_lifetime": 4}).json()
    assert comparison["n_steps"] == 2 * N_GEN + 1
    assert comparison["long_lifetime"] == 4
    methods = {m["method"]: m for m in comparison["methods"]}
    assert list(methods) == ["zigzag", "t1", "t1o", "t2"]
    zigzag = client.get(f"{url}/bars", params={"dimension": 0}).json()
    assert methods["zigzag"]["n_bars"] == len(zigzag["bar"])
    assert methods["zigzag"]["agreement_step"] == 1.0
    for row in methods.values():
        assert len(row["at_least"]) == comparison["n_steps"]
        assert row["at_least"][0] == row["n_bars"]
        assert 0 <= row["agreement_step"] <= row["agreement_generation"] <= 1

    t2 = client.get(f"{url}/trackers/t2/bars").json()
    assert t2["method"] == "t2"
    assert len(t2["birth"]) == methods["t2"]["n_bars"]
    assert all(b % 2 == 0 for b in t2["birth"])  # survivors only: births at P_t
    assert len(t2["matched_step"]) == len(t2["matched_generation"]) == len(t2["birth"])
    shown = client.get(f"{url}/trackers/t1/bars", params={"min_lifetime": 3}).json()
    assert all(d - b >= 3 for b, d in zip(shown["birth"], shown["death"], strict=True))
    assert client.get(f"{url}/trackers/t3/bars").status_code == 422

    batch = client.get(
        f"/api/analysis-batches/{created[0]['batch_id']}/tracker-comparison",
        params={"epsilon_index": 1},
    ).json()
    assert (batch["n_runs"], batch["skipped"], batch["epsilon"]) == (2, 0, 0.3)
    assert set(batch["methods"]) == {"zigzag", "t1", "t1o", "t2"}
    assert all(len(values) == 2 for values in batch["methods"]["t1"].values())

    [group] = client.get(f"/api/experiments/{experiment['id']}/analysis-groups").json()
    grouped = client.get(
        f"/api/experiments/{experiment['id']}/analysis-groups/{group['key']}/tracker-comparison"
    ).json()
    assert grouped["n_runs"] == 2

    # results written before the trackers existed have no trackers file
    analysis = client.get(f"/api/analyses/{created[0]['id']}").json()
    (results,) = runs_dir.glob(f"*/analyses/{analysis['id']}/*/trackers.parquet")
    results.unlink()
    missing = client.get(f"{url}/trackers/comparison")
    assert missing.status_code == 404
    assert "run it again" in missing.text
    partial = client.get(f"/api/analysis-batches/{created[0]['batch_id']}/tracker-comparison")
    assert (partial.json()["n_runs"], partial.json()["skipped"]) == (1, 1)


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
    assert len(scales) == 3
    # based on the population's spacing, wider than the parent-offspring spacing of R_t
    assert scales[0] > suggestion["median_nearest_neighbour"]
