import numpy as np
import pytest
from pymoo.algorithms.moo import nsga2 as pymoo_nsga2
from pymoo.algorithms.moo import nsga3 as pymoo_nsga3
from pymoo.optimize import minimize
from pymoo.problems import get_problem

from esphea.algorithms import NSGA2, NSGA3, SMSEMOA, das_dennis, nsga3_population_size
from esphea.core import (
    AlgorithmObserver,
    EvolutionaryAlgorithm,
    GenerationRecord,
    MaxGenerations,
    Population,
)
from esphea.metrics import IGD
from esphea.problems import DTLZ2


class RecordingObserver(AlgorithmObserver):
    def __init__(self) -> None:
        self.initial: Population | None = None
        self.records: list[GenerationRecord] = []
        self.finished_at: int | None = None

    def on_start(self, initial: Population) -> None:
        self.initial = initial

    def on_generation(self, record: GenerationRecord) -> None:
        self.records.append(record)

    def on_finish(self, final: Population, generations: int) -> None:
        self.finished_at = generations


def build(name: str, problem: DTLZ2) -> EvolutionaryAlgorithm:
    if name == "nsga2":
        return NSGA2(problem, pop_size=92)
    if name == "smsemoa":
        return SMSEMOA(problem, pop_size=92)
    return NSGA3(problem, ref_dirs=das_dennis(problem.n_obj, 12))


ALGORITHMS = ["nsga2", "nsga3", "smsemoa"]


@pytest.mark.parametrize("name", ALGORITHMS)
def test_generation_records_are_consistent(name: str, dtlz2: DTLZ2) -> None:
    algorithm = build(name, dtlz2)
    observer = RecordingObserver()
    result = algorithm.run(MaxGenerations(5), np.random.default_rng(1), [observer])

    assert observer.initial is not None
    assert observer.finished_at == result.generations == 5
    assert [r.generation for r in observer.records] == [1, 2, 3, 4, 5]

    previous = observer.initial
    n = algorithm.pop_size
    for record in observer.records:
        assert record.population is previous
        assert record.matings.shape == (algorithm.n_matings, 2)
        assert len(record.offspring) == n
        assert record.offspring_parents.shape == (n, 2)
        assert np.all((record.offspring_parents >= 0) & (record.offspring_parents < n))
        assert record.mutated.shape == (n,)
        assert len(np.unique(record.survivor_indices)) == n
        assert record.survived_mask().sum() == n
        assert record.times_selected().sum() == record.matings.size
        np.testing.assert_array_equal(
            record.survivors.X, record.merged().X[record.survivor_indices]
        )
        assert "rank" in record.survivors.attributes
        previous = record.survivors


@pytest.mark.parametrize("name", ALGORITHMS)
def test_same_seed_is_reproducible(name: str, dtlz2: DTLZ2) -> None:
    first = build(name, dtlz2).run(MaxGenerations(10), np.random.default_rng(7))
    second = build(name, dtlz2).run(MaxGenerations(10), np.random.default_rng(7))
    np.testing.assert_array_equal(first.final.F, second.final.F)


# Median IGD reached by pymoo's own implementations on this setting is about
# 0.074 (NSGA-II) and 0.053 (NSGA-III); thresholds leave room for seed noise.
@pytest.mark.parametrize(
    ("name", "max_igd"), [("nsga2", 0.09), ("nsga3", 0.065), ("smsemoa", 0.09)]
)
def test_converges_on_dtlz2(name: str, max_igd: float, dtlz2: DTLZ2) -> None:
    result = build(name, dtlz2).run(MaxGenerations(150), np.random.default_rng(3))
    igd = IGD(dtlz2.pareto_front(1000))(result.final.F)
    assert igd < max_igd


def test_nsga3_default_population_follows_deb_and_jain(dtlz2: DTLZ2) -> None:
    ref_dirs = das_dennis(3, 12)
    assert len(ref_dirs) == 91
    assert NSGA3(dtlz2, ref_dirs).pop_size == nsga3_population_size(91) == 92
    with pytest.raises(ValueError, match="reference directions"):
        NSGA3(dtlz2, ref_dirs, pop_size=80)


@pytest.mark.slow
@pytest.mark.parametrize("name", ["nsga2", "nsga3"])
def test_statistically_comparable_to_pymoo(name: str, dtlz2: DTLZ2) -> None:
    """Median final IGD over independent runs must match pymoo's own implementation."""
    n_runs, n_gen = 11, 200
    ref_dirs = das_dennis(3, 12)
    indicator = IGD(dtlz2.pareto_front(1000))
    reference = get_problem("dtlz2", n_var=dtlz2.n_var, n_obj=3)

    ours, theirs = [], []
    for seed in range(n_runs):
        result = build(name, dtlz2).run(MaxGenerations(n_gen), np.random.default_rng(seed))
        ours.append(indicator(result.final.F))
        native = (
            pymoo_nsga2.NSGA2(pop_size=92)
            if name == "nsga2"
            else pymoo_nsga3.NSGA3(ref_dirs=ref_dirs, pop_size=92)
        )
        res = minimize(reference, native, ("n_gen", n_gen), seed=seed, verbose=False)
        theirs.append(indicator(res.pop.get("F")))

    assert np.median(ours) == pytest.approx(np.median(theirs), rel=0.15)
