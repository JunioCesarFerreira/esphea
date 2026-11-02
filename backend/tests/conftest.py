import numpy as np
import pytest

from esphea.problems import DTLZ2


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(12345)


@pytest.fixture
def dtlz2() -> DTLZ2:
    return DTLZ2(n_obj=3, k=10)
