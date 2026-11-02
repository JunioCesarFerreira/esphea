from pathlib import Path

import numpy as np
import pytest

from esphea.algorithms import NSGA2
from esphea.core import MaxGenerations
from esphea.experiments.observers import SnapshotObserver
from esphea.experiments.storage import SnapshotReader, SnapshotWriter
from esphea.problems import DTLZ2
from esphea.topology.analysis import AnalysisInterruptedError, TopologyAnalyzer, evenly_spaced
from esphea.topology.clouds import Identity, PointCloudKind, Survivors
from esphea.topology.config import TopologyAnalysisConfig
from esphea.topology.distances import BottleneckDistance, WassersteinDistance
from esphea.topology.persistence import VietorisRips
from esphea.topology.storage import TopologyResultReader, TopologyResultWriter

N_GEN = 6


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("run")
    problem = DTLZ2(n_obj=3, k=5)
    writer = SnapshotWriter(directory, n_var=problem.n_var, n_obj=3, generations_per_part=4)
    NSGA2(problem, pop_size=24).run(
        MaxGenerations(N_GEN), np.random.default_rng(0), [SnapshotObserver(writer)]
    )
    return directory


def analyse(snapshots: Path, tmp_path: Path, **overrides: object) -> TopologyResultReader:
    config = TopologyAnalysisConfig.model_validate({"max_epsilon": 3.0, **overrides})
    analyzer = TopologyAnalyzer(
        config,
        computer=VietorisRips(),
        distances=[BottleneckDistance(), WassersteinDistance(1)],
        normalizer=Identity(),
    )
    out = tmp_path / "analysis"
    writer = TopologyResultWriter(
        out,
        max_dimension=config.max_dimension,
        max_epsilon=config.max_epsilon,
        metrics=analyzer.metric_names,
    )
    analyzer.analyze(SnapshotReader(snapshots), writer)
    return TopologyResultReader(out)


def test_every_generation_is_analysed(snapshots: Path, tmp_path: Path) -> None:
    result = analyse(snapshots, tmp_path)
    assert result.generations == list(range(N_GEN + 1))
    assert result.metrics == ["bottleneck", "wasserstein_1"]

    clouds = result.clouds().to_pydict()
    assert clouds["n_points"] == [24] * (N_GEN + 1)
    assert np.isnan(clouds["hausdorff_previous"][0])
    assert clouds["hausdorff_final"][-1] == 0.0

    series = result.series().to_pydict()
    assert len(series["generation"]) == 2 * (N_GEN + 1)  # H0 and H1
    finals = [
        v
        for v, g in zip(series["bottleneck_final"], series["generation"], strict=True)
        if g == N_GEN
    ]
    assert finals == [0.0, 0.0]


def test_stability_bound_holds_between_consecutive_generations(
    snapshots: Path, tmp_path: Path
) -> None:
    result = analyse(snapshots, tmp_path)
    hausdorff = dict(
        zip(
            result.clouds().column("generation").to_pylist(),
            result.clouds().column("hausdorff_previous").to_pylist(),
            strict=True,
        )
    )
    series = result.series().to_pydict()
    for g, d_b in zip(series["generation"], series["bottleneck_previous"], strict=True):
        if g > 0:
            assert d_b <= 2 * hausdorff[g] + 1e-9


def test_diagram_and_betti_curves_round_trip(snapshots: Path, tmp_path: Path) -> None:
    result = analyse(snapshots, tmp_path)
    diagram = result.diagram(3)
    assert diagram.max_dimension == 1
    assert diagram.truncated[0].sum() == 1  # max_epsilon above the diameter: one component left
    grid, curves = result.betti_curves(0, resolution=50)
    assert grid[-1] == 3.0
    assert curves.shape == (N_GEN + 1, 50)
    # At scale 0 every *distinct* point is a component (clones merge immediately).
    clouds = (Survivors().select(s) for s in SnapshotReader(snapshots).iter_generations())
    distinct = [np.unique(cloud, axis=0).shape[0] for cloud in clouds]
    np.testing.assert_array_equal(curves[:, 0], distinct)
    assert np.all(curves[:, -1] == 1)


def test_distance_matrix(snapshots: Path, tmp_path: Path) -> None:
    result = analyse(snapshots, tmp_path, distance_matrix=True, point_cloud=PointCloudKind.MERGED)
    generations, matrix = result.matrix(1, "bottleneck")
    assert generations == list(range(N_GEN + 1))
    np.testing.assert_allclose(matrix, matrix.T)
    np.testing.assert_allclose(np.diag(matrix), 0.0)
    assert result.clouds().column("n_points").to_pylist()[1:] == [48] * N_GEN


def test_missing_matrix_and_generation(snapshots: Path, tmp_path: Path) -> None:
    result = analyse(snapshots, tmp_path, max_dimension=0)
    with pytest.raises(KeyError, match="matrix"):
        result.matrix(0, "bottleneck")
    with pytest.raises(KeyError):
        result.diagram(99)


def test_interruption_leaves_no_results(snapshots: Path, tmp_path: Path) -> None:
    config = TopologyAnalysisConfig(max_epsilon=1.0)
    analyzer = TopologyAnalyzer(
        config, computer=VietorisRips(), distances=[BottleneckDistance()], normalizer=Identity()
    )
    out = tmp_path / "analysis"
    writer = TopologyResultWriter(out, max_dimension=1, max_epsilon=1.0, metrics=["bottleneck"])
    with pytest.raises(AnalysisInterruptedError):
        analyzer.analyze(SnapshotReader(snapshots), writer, should_stop=lambda: True)
    assert not out.exists()


def test_evenly_spaced() -> None:
    assert evenly_spaced([0, 1, 2], 5) == [0, 1, 2]
    picked = evenly_spaced(list(range(1000)), 100)
    assert len(picked) == 100
    assert picked[0] == 0
    assert picked[-1] == 999
