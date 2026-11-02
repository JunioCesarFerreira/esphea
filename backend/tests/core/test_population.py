import numpy as np
import pytest

from esphea.core import Population


def make_population(n: int = 5) -> Population:
    X = np.arange(n * 3, dtype=np.float64).reshape(n, 3)
    F = np.arange(n * 2, dtype=np.float64).reshape(n, 2)
    return Population(X=X, F=F, attributes={"rank": np.arange(n)})


def test_arrays_are_read_only() -> None:
    pop = make_population()
    with pytest.raises(ValueError, match="read-only"):
        pop.X[0, 0] = 1.0
    with pytest.raises(ValueError, match="read-only"):
        pop.attribute("rank")[0] = 3


def test_take_slices_every_array() -> None:
    pop = make_population()
    sub = pop.take(np.array([4, 1]))
    np.testing.assert_array_equal(sub.X, pop.X[[4, 1]])
    np.testing.assert_array_equal(sub.F, pop.F[[4, 1]])
    np.testing.assert_array_equal(sub.attribute("rank"), [4, 1])


def test_concat_drops_attributes() -> None:
    pop = make_population()
    merged = Population.concat(pop, pop)
    assert len(merged) == 10
    assert dict(merged.attributes) == {}


def test_shape_validation() -> None:
    with pytest.raises(ValueError, match="rows"):
        Population(X=np.zeros((3, 2)), F=np.zeros((2, 2)))
    with pytest.raises(ValueError, match="attribute 'rank'"):
        Population(X=np.zeros((3, 2)), F=np.zeros((3, 2)), attributes={"rank": np.zeros(2)})


def test_missing_attribute_message_lists_available() -> None:
    with pytest.raises(KeyError, match="available: rank"):
        make_population().attribute("crowding")
