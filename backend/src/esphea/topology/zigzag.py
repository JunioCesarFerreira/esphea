"""Zigzag persistent homology of an evolving population.

The zigzag of a run is the sequence of inclusions

    P_0 -> R_1 <- P_1 -> R_2 <- P_2 -> ... <- P_T,   R_t = P_{t-1} + Q_t,

numbered by *steps* ``k``: ``P_0`` is step 0, ``R_t`` step ``2t - 1`` and ``P_t``
step ``2t``. Every set is turned into its Vietoris-Rips complex at a fixed scale
``epsilon`` (edge length), and individuals keep their identity along the
sequence, so the complexes are nested exactly like the sets.

A bar is alive on the steps ``[birth, death - 1]``. Because forward arrows only
insert simplices (offspring) and backward arrows only remove them (discarded
individuals), every birth and death has a cause:

* born on an ``R`` step: created by **variation** (offspring), e.g. a new niche;
* born on a ``P`` step: created by **selection** (removal), e.g. a split;
* dies entering an ``R`` step: killed by **variation**, e.g. offspring bridging niches;
* dies entering a ``P`` step: killed by **selection**, e.g. a niche wiped out.

The complex taken at ``R_t`` is either

* ``rips``: ``VR(R_t)``, every candidate. The zigzag records what each generation
  builds and destroys, including the niches joined and the holes filled or opened by
  offspring that selection discards at once; or
* ``union``: ``VR(P_{t-1} + P_t)``, the parents and the survivors, which leaves out the
  offspring discarded at ``t``. This is the union zigzag
  ``P_{t-1} -> P_{t-1} + P_t <- P_t``: it follows the features of the populations
  themselves, whatever individuals carry them, since a class of ``P_{t-1}`` and one of
  ``P_t`` are the same feature exactly when their images in ``VR(P_{t-1} + P_t)`` agree.
  Its causes refer to the survivors: a birth on an ``R`` step is a feature that a
  surviving offspring creates.

``VR(P_{t-1} + P_t)`` is the subcomplex of ``VR(R_t)`` induced by the parents and the
survivors, not the union of the two complexes ``VR(P_{t-1}) + VR(P_t)``, which would
also drop the edges from a discarded parent to the offspring that replaces it: a loop
handed over from one to the other would split.

``bridge`` and ``bridge_union`` name retired complexes (a base joined by a spanning
forest of the other edges of ``VR(R_t)``, with the ``H_0`` of ``rips``); they are kept
only to read the analyses stored with them.

Computed with Dionysus' fast zigzag (Dey and Hou, 2022), which reduces the
zigzag to the extended persistence of a cone.
"""

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import dionysus
import numpy as np
from dionysus.zigzag import apex, point_representative
from scipy.spatial import cKDTree

from esphea.core.types import BoolArray, FloatArray, IntArray
from esphea.experiments.storage import SnapshotReader
from esphea.topology.clouds import Normalizer

CONE_VERTEX = -1
REPRESENTATIVES_MAX_SIMPLICES = 500_000
"""Representatives need a reduction that keeps the V matrix, which grows much faster than
the barcode alone (measured: 0.2 M simplices ~8 s, 0.8 M ~60 s and 2.4 GB). Above this
size representatives are skipped and only the barcode is computed."""


class Cause(StrEnum):
    INITIAL = "initial"  # present in P_0
    VARIATION = "variation"  # forward arrow P_{t-1} -> R_t (offspring inserted)
    SELECTION = "selection"  # backward arrow R_t <- P_t (individuals removed)
    END = "end"  # still alive in P_T


class MiddleComplex(StrEnum):
    """Complex taken at every ``R_t`` (``P_t`` is always the Vietoris-Rips complex of ``P_t``)."""

    RIPS = "rips"  # VR(R_t)
    UNION = "union"  # VR(P_{t-1} + P_t): the offspring discarded at t are left out
    # retired bridge complexes, kept only to read the analyses stored with them
    BRIDGE = "bridge"
    BRIDGE_UNION = "bridge_union"

    @property
    def retired(self) -> bool:
        return self in (MiddleComplex.BRIDGE, MiddleComplex.BRIDGE_UNION)


class SimplexBudgetExceededError(ValueError):
    """The complexes would hold more simplices than allowed (memory guard)."""


def step_of_r(generation: int) -> int:
    return 2 * generation - 1


def step_of_p(generation: int) -> int:
    return 2 * generation


def step_generation(step: int) -> int:
    """Generation of the set at ``step`` (``R_t`` and ``P_t`` both belong to ``t``)."""
    return (step + 1) // 2


def is_r_step(step: int) -> bool:
    return step % 2 == 1


def discarded_offspring(first: IntArray, last: IntArray) -> BoolArray:
    """Which individuals are offspring discarded on the ``R`` step they were created in."""
    discarded: BoolArray = (first == last) & (first % 2 == 1)
    return discarded


def complex_members(first: IntArray, last: IntArray, step: int, middle: MiddleComplex) -> IntArray:
    """Individuals that are vertices of the complex taken at ``step``.

    The ``union`` complex at ``R_t`` leaves out the offspring discarded at ``t``.
    """
    present = (first <= step) & (last >= step)
    if middle == MiddleComplex.UNION:
        present &= ~discarded_offspring(first, last)
    return np.flatnonzero(present)


@dataclass(frozen=True, slots=True)
class ZigzagSequence:
    """Individuals of a run with the contiguous range of steps they are present in.

    Attributes:
        points: Objective vectors, one row per run-unique individual id.
        first: First step each individual is present in.
        last: Last step each individual is present in.
        n_generations: ``T`` (the sequence ends with ``P_T``).
    """

    points: FloatArray
    first: IntArray
    last: IntArray
    n_generations: int

    @property
    def n_steps(self) -> int:
        return 2 * self.n_generations + 1

    def members(self, step: int) -> IntArray:
        return np.flatnonzero((self.first <= step) & (self.last >= step))

    def vertices(self, step: int, middle: MiddleComplex) -> IntArray:
        """Members that are vertices of the complex taken at ``step`` (see ``complex_members``)."""
        return complex_members(self.first, self.last, step, middle)

    @classmethod
    def from_snapshots(cls, reader: SnapshotReader, normalizer: Normalizer) -> "ZigzagSequence":
        """Build from snapshots stored at every generation with individual ids."""
        if not reader.has_individual_ids:
            raise ValueError(
                "this run was stored without individual identities; run it again to analyse it"
            )
        generations = reader.generations()
        if generations != list(range(len(generations))):
            raise ValueError("the zigzag needs every generation stored (snapshot every 1)")
        points: dict[int, FloatArray] = {}
        first: dict[int, int] = {}
        last: dict[int, int] = {}
        for snapshot in reader.iter_generations():
            g = snapshot.generation
            population, offspring = snapshot.population, snapshot.offspring
            assert population.ids is not None
            if offspring is None:  # P_0
                for i, f in zip(population.ids.tolist(), population.F, strict=True):
                    points[i], first[i], last[i] = f, 0, 0
                continue
            assert offspring.ids is not None
            for i, f in zip(offspring.ids.tolist(), offspring.F, strict=True):
                points[i], first[i] = f, step_of_r(g)
            ids = np.concatenate((population.ids, offspring.ids)).tolist()
            survived = np.concatenate((population.survived, offspring.survived)).tolist()
            for i, kept in zip(ids, survived, strict=True):
                last[i] = step_of_p(g) if kept else step_of_r(g)
        n_ids = max(points) + 1
        if len(points) != n_ids:
            raise ValueError("individual ids are not contiguous")
        order = range(n_ids)
        return cls(
            points=normalizer.transform(np.array([points[i] for i in order])),
            first=np.array([first[i] for i in order], dtype=np.intp),
            last=np.array([last[i] for i in order], dtype=np.intp),
            n_generations=len(generations) - 1,
        )


def zigzag_complex(
    sequence: ZigzagSequence,
    epsilon: float,
    max_dimension: int,
    *,
    max_simplices: int,
    middle: MiddleComplex = MiddleComplex.RIPS,
    should_stop: Callable[[], bool] = lambda: False,
) -> tuple[list[list[int]], list[list[int]]]:
    """Simplices of the zigzag of Vietoris-Rips complexes and their presence times.

    Every set of the sequence is contained in some ``R_t``, so the simplices
    are enumerated per ``R_t`` (cliques of the epsilon-neighbourhood graph up to
    ``max_dimension + 1``) over the vertices of the complex taken there. A simplex is
    present while all its vertices are, i.e. on ``[max first, min last]``; Dionysus
    receives ``[insert, remove)``. The ``union`` complex has no simplex through an
    offspring discarded at once, not even its vertex.
    """
    if middle.retired:
        raise ValueError(f"the '{middle}' complex was retired; use 'rips' or 'union'")
    seen: dict[tuple[int, ...], None] = {}
    for generation in range(1, sequence.n_generations + 1):
        if should_stop():
            raise InterruptedError("the zigzag analysis was asked to stop")
        ids = sequence.vertices(step_of_r(generation), middle)
        pairs = cKDTree(sequence.points[ids]).query_pairs(epsilon, output_type="ndarray")
        cliques = [tuple(sorted((int(ids[a]), int(ids[b])))) for a, b in pairs]
        neighbours: dict[int, set[int]] = {}
        for a, b in cliques:
            neighbours.setdefault(a, set()).add(b)
            neighbours.setdefault(b, set()).add(a)
        for size in range(2, max_dimension + 3):
            if size > 2:  # extend (size-1)-cliques by a common neighbour above their last vertex
                cliques = [
                    (*clique, v)
                    for clique in cliques
                    for v in set.intersection(*(neighbours[u] for u in clique))
                    if v > clique[-1]
                ]
            for clique in cliques:
                seen[clique] = None
            if len(seen) > max_simplices:
                raise SimplexBudgetExceededError(
                    f"more than {max_simplices:,} simplices at epsilon {epsilon:g}: "
                    "use a smaller epsilon or a lower homology dimension"
                )
    left_out = (
        discarded_offspring(sequence.first, sequence.last)
        if middle == MiddleComplex.UNION
        else np.zeros(sequence.points.shape[0], dtype=np.bool_)
    )
    vertices = np.flatnonzero(~left_out).tolist()
    simplices: list[list[int]] = [[v] for v in vertices]
    times: list[list[int]] = [[int(sequence.first[v]), int(sequence.last[v]) + 1] for v in vertices]
    for simplex in seen:
        start = int(max(sequence.first[v] for v in simplex))
        end = int(min(sequence.last[v] for v in simplex))
        if start <= end:
            simplices.append(list(simplex))
            times.append([start, end + 1])
    return simplices, times


@dataclass(frozen=True, slots=True)
class ZigzagBar:
    """A feature alive on steps ``[birth, death - 1]`` (``death = n_steps``: alive at the end)."""

    dimension: int
    birth: int
    death: int
    kind: str  # Dionysus interval type: "cc", "co", "oc" or "oo"
    birth_cause: Cause
    death_cause: Cause

    @property
    def lifetime(self) -> int:
        """Number of steps the feature is alive in."""
        return self.death - self.birth


@dataclass(frozen=True, slots=True)
class RepresentativeSegment:
    """Representative cycle of a bar, constant on steps ``[start, end]``."""

    start: int
    end: int
    simplices: tuple[tuple[int, ...], ...]  # vertices are individual ids


@dataclass(slots=True)
class ZigzagResult:
    epsilon: float
    n_steps: int
    n_simplices: int = 0
    middle: MiddleComplex = MiddleComplex.RIPS
    bars: list[ZigzagBar] = field(default_factory=list)
    # why representatives were not extracted (None when they were, or none were asked for)
    representatives_skipped: str | None = None
    # index into ``bars`` -> representative segments (empty if unavailable)
    representatives: dict[int, list[RepresentativeSegment]] = field(default_factory=dict)


def _birth_cause(step: int) -> Cause:
    if step == 0:
        return Cause.INITIAL
    return Cause.VARIATION if is_r_step(step) else Cause.SELECTION


def _death_cause(step: int, n_steps: int) -> Cause:
    if step >= n_steps:
        return Cause.END
    return Cause.VARIATION if is_r_step(step) else Cause.SELECTION


def compute_zigzag(
    sequence: ZigzagSequence,
    epsilon: float,
    max_dimension: int,
    *,
    max_simplices: int,
    middle: MiddleComplex = MiddleComplex.RIPS,
    representatives: int = 0,
    max_representative_simplices: int = REPRESENTATIVES_MAX_SIMPLICES,
    should_stop: Callable[[], bool] = lambda: False,
) -> ZigzagResult:
    """Zigzag barcodes of ``H_0 .. H_max_dimension`` at scale ``epsilon``.

    ``middle`` is the complex taken at every ``R_t`` (see the module docstring).
    ``representatives`` is the number of longest bars per dimension (alive on at
    least two steps) whose representative cycles are extracted, as long as the
    complex has at most ``max_representative_simplices`` simplices.
    """
    simplices, times = zigzag_complex(
        sequence,
        epsilon,
        max_dimension,
        max_simplices=max_simplices,
        middle=middle,
        should_stop=should_stop,
    )
    n_steps = sequence.n_steps
    result = ZigzagResult(
        epsilon=epsilon,
        n_steps=n_steps,
        n_simplices=len(simplices),
        middle=middle,
    )
    with_representatives = representatives > 0 and len(simplices) <= max_representative_simplices
    if representatives > 0 and not with_representatives:
        result.representatives_skipped = (
            f"{len(simplices):,} simplices exceed the {max_representative_simplices:,} "
            "allowed for representatives; use a smaller epsilon to obtain them"
        )
    cone = dionysus.fast_zigzag(simplices, times)
    if with_representatives:
        reduced, v = dionysus.homology_persistence(cone, method="matrix_v")
    else:
        reduced, v = dionysus.homology_persistence(cone, method="clearing"), None
    diagrams = dionysus.init_zigzag_diagrams(reduced, cone)

    points: list[object] = []
    for dimension in range(max_dimension + 1):
        dimension_diagrams = diagrams[dimension] if dimension < len(diagrams) else {}
        for kind, diagram in dimension_diagrams.items():
            for point in diagram:
                birth = int(point.birth)
                death = n_steps if np.isinf(point.death) else min(int(point.death), n_steps)
                result.bars.append(
                    ZigzagBar(
                        dimension=dimension,
                        birth=birth,
                        death=death,
                        kind=kind,
                        birth_cause=_birth_cause(birth),
                        death_cause=_death_cause(death, n_steps),
                    )
                )
                points.append(point)

    if with_representatives:
        for dimension in range(max_dimension + 1):
            longest = sorted(
                (
                    i
                    for i, bar in enumerate(result.bars)
                    if bar.dimension == dimension and bar.lifetime >= 2
                ),
                key=lambda i: -result.bars[i].lifetime,
            )[:representatives]
            for index in longest:
                bar = result.bars[index]
                representative = apex(points[index], reduced, v, cone)
                result.representatives[index] = list(
                    _segments(representative, cone, range(bar.birth, bar.death))
                )
    return result


def _segments(
    representative: object, cone: object, steps: Sequence[int]
) -> Iterator[RepresentativeSegment]:
    """Sample the representative on each step and merge consecutive equal samples."""
    current: tuple[tuple[int, ...], ...] | None = None
    start = steps[0] if steps else 0
    for step in steps:
        chain = point_representative(representative, step + 0.5)
        simplices = tuple(
            sorted(
                tuple(sorted(int(v) for v in cone[index]))  # type: ignore[index]
                for index, _ in chain
                if CONE_VERTEX not in cone[index]  # type: ignore[index]
            )
        )
        if simplices != current:
            if current:
                yield RepresentativeSegment(start, step - 1, current)
            current, start = simplices, step
    if current:
        yield RepresentativeSegment(start, steps[-1], current)


def epsilon_components(
    points: FloatArray, members: IntArray, epsilon: float, seeds: set[int]
) -> IntArray:
    """Members connected (within ``epsilon`` steps) to any of the ``seeds`` individuals."""
    index = {int(m): i for i, m in enumerate(members)}
    pairs = cKDTree(points[members]).query_pairs(epsilon, output_type="ndarray")
    neighbours: dict[int, list[int]] = {}
    for a, b in pairs:
        neighbours.setdefault(int(a), []).append(int(b))
        neighbours.setdefault(int(b), []).append(int(a))
    frontier = [index[s] for s in seeds if s in index]
    reached = set(frontier)
    while frontier:
        node = frontier.pop()
        for other in neighbours.get(node, []):
            if other not in reached:
                reached.add(other)
                frontier.append(other)
    return np.sort(members[sorted(reached)]).astype(np.intp)
