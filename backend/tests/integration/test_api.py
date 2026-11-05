import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from esphea.messaging.ports import JobKind
from esphea.services.execution import RunService
from tests.integration.conftest import FakeFlags, FakePublisher, FakeSubscriber, RecordingQueue


def experiment_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "name": "DTLZ2 smoke",
        "problem": {"name": "dtlz2", "n_obj": 3, "k": 5},
        "algorithm": {"name": "nsga3", "n_partitions": 4},
        "n_gen": 6,
        "n_runs": 2,
        "seed": 1,
    }
    body.update(overrides)
    return body


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"


def test_catalog_lists_defaults(client: TestClient) -> None:
    catalog = client.get("/api/catalog").json()
    assert [p["name"] for p in catalog["problems"]] == ["dtlz2", "dtlz7", "zdt1", "zdt3", "zdt4"]
    assert [a["name"] for a in catalog["algorithms"]] == ["nsga2", "nsga3", "smsemoa"]


def test_preview_derives_quantities(client: TestClient) -> None:
    preview = client.post("/api/experiments/preview", json=experiment_body()).json()
    assert preview["n_var"] == 7
    assert preview["n_reference_directions"] == 15
    assert preview["pop_size"] == 16
    assert (
        preview["estimated_snapshot_bytes_total"] == 2 * preview["estimated_snapshot_bytes_per_run"]
    )


def test_preview_rejects_invalid_configuration(client: TestClient) -> None:
    body = experiment_body(algorithm={"name": "nsga3", "n_partitions": 4, "pop_size": 8})
    response = client.post("/api/experiments/preview", json=body)
    assert response.status_code == 422
    assert "reference directions" in response.text


def test_create_enqueues_one_job_per_run(client: TestClient, queue: RecordingQueue) -> None:
    created = client.post("/api/experiments", json=experiment_body()).json()
    assert created["status"] == "queued"
    assert [(run["id"], 1) for run in created["runs"]] == [(str(r), a) for r, a in queue.runs()]
    assert all(run["attempt"] == 0 for run in created["runs"])
    assert len({run["seed"] for run in created["runs"]}) == 2

    listed = client.get("/api/experiments").json()
    assert [e["id"] for e in listed] == [created["id"]]
    assert listed[0]["run_counts"]["queued"] == 2


def test_full_lifecycle_with_inline_execution(
    client: TestClient, queue: RecordingQueue, run_service: RunService, publisher: FakePublisher
) -> None:
    queue.executors[JobKind.RUN] = run_service
    experiment = client.post("/api/experiments", json=experiment_body()).json()
    detail = client.get(f"/api/experiments/{experiment['id']}").json()
    assert detail["status"] == "completed"
    assert detail["progress"] == 1.0
    run_id = detail["runs"][0]["id"]

    metrics = client.get(f"/api/runs/{run_id}/metrics").json()
    assert metrics["generation"] == list(range(7))
    assert set(metrics["values"]) == {
        "decision_inertia",
        "gd",
        "hv",
        "hv_offspring",
        "igd",
        "igd_plus",
        "mean_distance",
        "spacing",
        "spread",
    }

    summary = client.get(f"/api/experiments/{experiment['id']}/metrics").json()
    assert summary["igd"]["n_runs"] == [2] * 7

    generations = client.get(f"/api/runs/{run_id}/generations").json()["generations"]
    assert generations == list(range(7))
    snapshot = client.get(
        f"/api/runs/{run_id}/generations/3", params={"decision_variables": True}
    ).json()
    assert len(snapshot["population"]["F"]) == 16
    assert len(snapshot["offspring"]["X"][0]) == 7
    assert sum(snapshot["population"]["survived"]) + sum(snapshot["offspring"]["survived"]) == 16

    csv_text = client.get(f"/api/runs/{run_id}/metrics.csv").text
    header = (
        "generation,n_nondominated,elapsed_seconds,decision_inertia,gd,hv,hv_offspring,"
        "igd,igd_plus,mean_distance,spacing,spread"
    )
    assert csv_text.splitlines()[0] == header

    front = client.get(
        f"/api/experiments/{experiment['id']}/pareto-front", params={"n_points": 50}
    ).json()
    assert len(front["points"]) >= 50

    types = {event["type"] for event in publisher.events}
    assert types == {"run.status", "run.progress"}


def test_cancel_queued_and_running_runs(
    client: TestClient, queue: RecordingQueue, flags: FakeFlags
) -> None:
    experiment = client.post("/api/experiments", json=experiment_body()).json()
    cancelled = client.post(f"/api/experiments/{experiment['id']}/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert sorted((str(j.entity_id), j.attempt) for j in queue.cancelled) == sorted(
        (r["id"], 1) for r in experiment["runs"]
    )
    assert flags.requested == set()


def test_delete_requires_inactive_experiment(client: TestClient) -> None:
    experiment = client.post("/api/experiments", json=experiment_body()).json()
    url = f"/api/experiments/{experiment['id']}"
    assert client.delete(url).status_code == 409
    client.post(f"{url}/cancel")
    assert client.delete(url).status_code == 204
    assert client.get(url).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/api/experiments/00000000-0000-0000-0000-000000000000",
        "/api/runs/00000000-0000-0000-0000-000000000000/metrics",
        "/api/runs/00000000-0000-0000-0000-000000000000/generations",
    ],
)
def test_unknown_resources_return_404(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 404


def test_events_websocket_forwards_messages(client: TestClient, subscriber: FakeSubscriber) -> None:
    subscriber.messages = [json.dumps({"type": "run.status"}), json.dumps({"type": "run.progress"})]
    url = "/api/experiments/00000000-0000-0000-0000-000000000000/events"
    with client.websocket_connect(url) as websocket:
        assert websocket.receive_json() == {"type": "run.status"}
        assert websocket.receive_json() == {"type": "run.progress"}
