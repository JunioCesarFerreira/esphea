import numpy as np
import pytest

from esphea.experiments.storage import GenerationSnapshot, SnapshotGroup
from esphea.topology.clouds import (
    SELECTORS,
    FixedScaling,
    Identity,
    PerCloudMinMax,
    PointCloudKind,
)


def group(F: list[list[float]], survived: list[bool], rank: list[int]) -> SnapshotGroup:
    n = len(F)
    return SnapshotGroup(
        F=np.array(F),
        X=None,
        survived=np.array(survived),
        rank=np.array(rank),
        times_selected=np.zeros(n, dtype=np.intp),
        parents=np.full((n, 2), -1),
        mutated=np.zeros(n, dtype=bool),
    )


SNAPSHOT = GenerationSnapshot(
    generation=4,
    population=group([[0, 1], [1, 1]], [True, False], [0, -1]),
    offspring=group([[1, 0], [2, 2]], [True, True], [0, 1]),
)


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (PointCloudKind.SURVIVORS, [[0, 1], [1, 0], [2, 2]]),
        (PointCloudKind.MERGED, [[0, 1], [1, 1], [1, 0], [2, 2]]),
        (PointCloudKind.FIRST_FRONT, [[0, 1], [1, 0]]),
    ],
)
def test_selectors(kind: PointCloudKind, expected: list[list[float]]) -> None:
    np.testing.assert_array_equal(SELECTORS[kind].select(SNAPSHOT), expected)


def test_initial_generation_has_only_the_population() -> None:
    initial = GenerationSnapshot(0, group([[0, 1], [1, 0]], [True, True], [0, 0]), None)
    for selector in SELECTORS.values():
        assert selector.select(initial).shape == (2, 2)


def test_normalizers() -> None:
    points = np.array([[1.0, 2.0], [3.0, 6.0]])
    np.testing.assert_array_equal(Identity().transform(points), points)
    fixed = FixedScaling(np.zeros(2), np.array([2.0, 4.0]))
    np.testing.assert_array_equal(fixed.transform(points), [[0.5, 0.5], [1.5, 1.5]])
    np.testing.assert_array_equal(PerCloudMinMax().transform(points), [[0, 0], [1, 1]])
    np.testing.assert_array_equal(PerCloudMinMax().transform(points[:1]), [[0, 0]])
    with pytest.raises(ValueError, match="nadir"):
        FixedScaling(np.ones(2), np.ones(2))
