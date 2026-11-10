"""Heuristic niche trackers, computed beside the zigzag ``H_0`` barcode to compare with it.

A niche is a connected component of the epsilon-neighbourhood graph of a set of
individuals, i.e. a class of ``H_0`` of its Vietoris-Rips complex at that scale.
The zigzag pairs the births and deaths of these classes globally. A tracker
links the components of consecutive sets through the individuals they share
and decides locally which bar continues:

* ``t1`` sees every set of the zigzag (``P_t`` and ``R_t``). At a merge the
  oldest bar continues (the elder rule of persistence; Edelsbrunner, Letscher
  and Zomorodian, 2002); at a split the largest fragment keeps the bar. This is
  the step-by-step tracking of components of tracking graphs (Bremer et al.,
  IEEE TVCG 17(9), 2011).
* ``t1o`` is ``t1`` except at a split, where the fragment holding the oldest
  individual keeps the bar.
* ``t2`` sees only the populations ``P_t`` and matches their components through
  shared survivors, as cluster and community trackers do (MONIC, Spiliopoulou et
  al., KDD 2006; Greene, Doyle and Cunningham, ASONAM 2010). It never sees
  ``R_t``, so births by offspring and merges through offspring are dated at
  ``P_t`` (step ``2t``), one step after the zigzag; matching bars by generation
  instead of by step removes that offset.

Bars follow the zigzag convention: alive on steps ``[birth, death - 1]``, and
``death = n_steps`` when alive at the end.
"""

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from esphea.core.types import BoolArray, FloatArray, IntArray
from esphea.topology.zigzag import MiddleComplex, ZigzagSequence, is_r_step, step_generation

ZIGZAG_METHOD = "zigzag"


class TrackerMethod(StrEnum):
    T1 = "t1"  # every step; elder rule at merges, largest fragment at splits
    T1O = "t1o"  # every step; elder rule at merges, oldest fragment at splits
    T2 = "t2"  # populations only, matched through shared survivors


class Resolution(StrEnum):
    STEP = "step"  # same birth and death step
    GENERATION = "generation"  # same birth and death generation (R_t and P_t are both t)


type Key = tuple[int, int]  # (birth step of the bar, smallest individual id at birth)


@dataclass(frozen=True, slots=True)
class _Components:
    members: IntArray  # sorted individual ids present at the step
    labels: IntArray  # component of each member, 0 .. count - 1
    count: int


def _components(points: FloatArray, members: IntArray, epsilon: float) -> _Components:
    n = len(members)
    if n == 0:
        return _Components(members, np.zeros(0, dtype=np.intp), 0)
    pairs = cKDTree(points[members]).query_pairs(epsilon, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    count, labels = connected_components(graph, directed=False)
    return _Components(members, labels.astype(np.intp), int(count))


def _key(step: int, components: _Components, label: int) -> Key:
    return step, int(components.members[components.labels == label].min())


def _bars(rows: list[tuple[int, int]]) -> IntArray:
    return np.array(rows, dtype=np.intp).reshape(-1, 2)


def _track_every_step(
    steps: Sequence[_Components], first: IntArray, *, oldest_fragment: bool
) -> IntArray:
    """``t1`` / ``t1o``: components of every ``P_t`` and ``R_t``."""
    closed: list[tuple[int, int]] = []
    current = steps[0]
    alive = {c: _key(0, current, c) for c in range(current.count)}
    for k in range(1, len(steps)):
        previous, current = current, steps[k]
        following: dict[int, Key] = {}
        if is_r_step(k):  # P_{t-1} inside R_t: components can only appear or merge
            label_of_previous = current.labels[np.searchsorted(current.members, previous.members)]
            parents: dict[int, set[int]] = {c: set() for c in range(current.count)}
            for old, new in zip(previous.labels.tolist(), label_of_previous.tolist(), strict=True):
                parents[new].add(old)
            for c, olds in parents.items():
                if not olds:
                    following[c] = _key(k, current, c)  # created by offspring
                    continue
                keep = min(olds, key=alive.__getitem__)  # elder rule
                following[c] = alive[keep]
                closed.extend((alive[p][0], k) for p in olds if p != keep)
        else:  # R_t contains P_t: components can only vanish or split
            parent_of_member = previous.labels[np.searchsorted(previous.members, current.members)]
            _, first_member = np.unique(current.labels, return_index=True)
            children: dict[int, list[int]] = {p: [] for p in range(previous.count)}
            for c, index in enumerate(first_member.tolist()):
                children[int(parent_of_member[index])].append(c)
            sizes = np.bincount(current.labels, minlength=current.count)
            for p, fragments in children.items():
                if not fragments:
                    closed.append((alive[p][0], k))  # removed by selection
                    continue
                if oldest_fragment:
                    keep = min(
                        fragments,
                        key=lambda c: int(first[current.members[current.labels == c]].min()),
                    )
                else:
                    keep = max(fragments, key=lambda c: (int(sizes[c]), -c))
                for c in fragments:
                    following[c] = alive[p] if c == keep else _key(k, current, c)
        alive = following
    closed.extend((birth, len(steps)) for birth, _ in alive.values())
    return _bars(closed)


def _track_populations(steps: Sequence[_Components]) -> IntArray:
    """``t2``: components of the populations ``P_t`` only, matched through survivors."""
    n_steps = len(steps)
    closed: list[tuple[int, int]] = []
    current = steps[0]
    alive = {c: _key(0, current, c) for c in range(current.count)}
    for k in range(2, n_steps, 2):
        previous, current = current, steps[k]
        _, now, before = np.intersect1d(
            current.members, previous.members, assume_unique=True, return_indices=True
        )
        parents: dict[int, set[int]] = {c: set() for c in range(current.count)}
        for new, old in zip(
            current.labels[now].tolist(), previous.labels[before].tolist(), strict=True
        ):
            parents[new].add(old)
        sizes = np.bincount(current.labels, minlength=current.count)
        claimed: set[int] = set()
        following: dict[int, Key] = {}
        for c in sorted(range(current.count), key=lambda c: -int(sizes[c])):  # largest first
            free = [p for p in parents[c] if p not in claimed]
            if free:
                keep = min(free, key=alive.__getitem__)
                claimed.add(keep)
                following[c] = alive[keep]
            else:
                following[c] = _key(k, current, c)
        closed.extend((key[0], k) for p, key in alive.items() if p not in claimed)
        alive = following
    closed.extend((birth, n_steps) for birth, _ in alive.values())
    return _bars(closed)


def track_niches(
    sequence: ZigzagSequence,
    epsilon: float,
    *,
    middle: MiddleComplex = MiddleComplex.RIPS,
    should_stop: Callable[[], bool] = lambda: False,
) -> dict[TrackerMethod, IntArray]:
    """Bars ``(birth, death)`` of every tracker at scale ``epsilon``, shape ``(n, 2)``.

    The trackers see the vertices of the zigzag's complexes (``middle``), so that they
    are compared with its ``H_0`` on the same sets.
    """
    steps = []
    for k in range(sequence.n_steps):
        if should_stop():
            raise InterruptedError("the zigzag analysis was asked to stop")
        steps.append(_components(sequence.points, sequence.vertices(k, middle), epsilon))
    return {
        TrackerMethod.T1: _track_every_step(steps, sequence.first, oldest_fragment=False),
        TrackerMethod.T1O: _track_every_step(steps, sequence.first, oldest_fragment=True),
        TrackerMethod.T2: _track_populations(steps),
    }


# --- comparison with the zigzag -------------------------------------------------------


def _keys(bars: IntArray, resolution: Resolution) -> list[tuple[int, int]]:
    if resolution == Resolution.STEP:
        return [(int(b), int(d)) for b, d in bars]
    return [(step_generation(int(b)), step_generation(int(d))) for b, d in bars]


def matched(bars: IntArray, reference: IntArray, resolution: Resolution) -> BoolArray:
    """Which ``bars`` have a counterpart in ``reference`` (each used once)."""
    available = Counter(_keys(reference, resolution))
    flags = np.zeros(len(bars), dtype=np.bool_)
    for i, key in enumerate(_keys(bars, resolution)):
        if available[key] > 0:
            available[key] -= 1
            flags[i] = True
    return flags


def agreement(reference: IntArray, bars: IntArray, resolution: Resolution) -> float | None:
    """Share of the ``reference`` bars reproduced by ``bars``; None without reference bars."""
    if len(reference) == 0:
        return None
    shared = Counter(_keys(reference, resolution)) & Counter(_keys(bars, resolution))
    return sum(shared.values()) / len(reference)


@dataclass(frozen=True, slots=True)
class MethodSummary:
    """One method's barcode, and how much of the zigzag barcode it reproduces.

    Lifetimes are in steps; quantiles use the bars that end before the last step.
    Long bars live at least ``long_lifetime`` steps (bars alive at the end included).
    """

    method: str
    n_bars: int
    n_long: int
    median_lifetime: float | None
    p90_lifetime: float | None
    agreement_step: float | None
    agreement_generation: float | None
    long_agreement_step: float | None
    long_agreement_generation: float | None
    at_least: list[int]  # bars alive at least L steps, L = 1 .. n_steps


def summarize(
    method: str, bars: IntArray, zigzag: IntArray, n_steps: int, long_lifetime: int
) -> MethodSummary:
    lifetime = bars[:, 1] - bars[:, 0]
    finite = lifetime[bars[:, 1] < n_steps]
    long_zigzag = zigzag[(zigzag[:, 1] - zigzag[:, 0]) >= long_lifetime]
    counts = np.bincount(lifetime, minlength=n_steps + 1)[: n_steps + 1]
    at_least = np.cumsum(counts[::-1])[::-1][1:]  # index L - 1 -> bars with lifetime >= L
    return MethodSummary(
        method=method,
        n_bars=len(bars),
        n_long=int(np.sum(lifetime >= long_lifetime)),
        median_lifetime=float(np.median(finite)) if len(finite) else None,
        p90_lifetime=float(np.percentile(finite, 90)) if len(finite) else None,
        agreement_step=agreement(zigzag, bars, Resolution.STEP),
        agreement_generation=agreement(zigzag, bars, Resolution.GENERATION),
        long_agreement_step=agreement(long_zigzag, bars, Resolution.STEP),
        long_agreement_generation=agreement(long_zigzag, bars, Resolution.GENERATION),
        at_least=[int(v) for v in at_least],
    )


def compare_with_zigzag(
    zigzag: IntArray, trackers: Mapping[str, IntArray], n_steps: int, long_lifetime: int
) -> list[MethodSummary]:
    """The zigzag first, then every tracker, summarised against the zigzag."""
    methods = {ZIGZAG_METHOD: zigzag, **trackers}
    return [summarize(name, bars, zigzag, n_steps, long_lifetime) for name, bars in methods.items()]
