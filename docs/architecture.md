# Architecture

This document describes how ESPHEA is organised, why, and how to extend it.

## Overview

```
┌────────────┐  HTTP / WebSocket  ┌────────────┐   RQ jobs   ┌────────────┐
│  frontend  │ ─────────────────▶ │    api     │ ──────────▶ │   worker   │ ×N
│ React + TS │ ◀───────────────── │  FastAPI   │   (Redis)   │  NumPy,    │
│  (nginx)   │   live events      └─────┬──────┘             │  pymoo,    │
└────────────┘                          │                    │  moocore   │
                                        │                    └─────┬──────┘
                                 ┌──────▼──────┐   Redis pub/sub   │
                                 │ PostgreSQL  │ ◀─────────────────┤
                                 │ experiments │                   │
                                 │ runs        │            ┌──────▼──────┐
                                 │ run_metrics │            │ ./data/runs │
                                 └─────────────┘            │  Parquet    │
                                                            └─────────────┘
```

| Service    | Responsibility                                                                 |
| ---------- | ------------------------------------------------------------------------------ |
| `frontend` | Static React build served by nginx, which also proxies `/api` to the API.     |
| `api`      | Validates configurations, manages experiments, serves results and live events. |
| `worker`   | Executes runs (one RQ job per run); scale with `docker compose up --scale worker=N`. |
| `migrate`  | One-shot Alembic migration before the API and workers start.                   |
| `postgres` | Experiment metadata, run status and per-generation indicator values.           |
| `redis`    | Job queue (RQ), live events (pub/sub) and cooperative cancellation flags.     |

## Backend layers

The backend (`backend/src/esphea`) is layered so that inner layers never import outer ones:

```
core            domain: Problem, Population, operator interfaces, the evolutionary loop
problems        benchmark problems (DTLZ2)
operators       concrete strategies (sampling, selection, SBX, PM, survival)
algorithms      NSGA-II and NSGA-III as compositions of strategies
metrics         quality indicators (IGD, IGD+, hypervolume)
experiments     configuration, registries, observers, snapshot storage, run executor
persistence     SQLAlchemy models and repositories
messaging       ports (protocols) for queue, events and cancellation + Redis/RQ adapters
services        use cases shared by the API and the worker
api, worker     delivery mechanisms (HTTP, RQ entry point)
```

### The evolutionary loop

`core.EvolutionaryAlgorithm` implements one elitist generational loop:

```
P_0 = rank(sample())
for t = 0, 1, ...:
    matings   = selection(P_t)                 # MatingSelection
    Q_t       = mutation(crossover(matings))   # Crossover, Mutation (with lineage)
    P_{t+1}   = survival(P_t ∪ Q_t)            # Survival
    notify observers with GenerationRecord(P_t, matings, Q_t, lineage, P_{t+1})
```

NSGA-II and NSGA-III are the same loop with different strategies:

|                  | NSGA-II                         | NSGA-III                                      |
| ---------------- | ------------------------------- | --------------------------------------------- |
| Mating selection | binary tournament (rank, crowding) | random                                     |
| Crossover        | SBX, η = 15, p = 0.9            | SBX, η = 30, p = 1                            |
| Mutation         | polynomial, η = 20, p = 1/n     | polynomial, η = 20, p = 1/n                   |
| Survival         | non-dominated sorting + crowding distance | non-dominated sorting + reference-point niching |
| Population       | user defined                    | smallest multiple of 4 ≥ number of Das–Dennis directions |

**Why pymoo is used for parts of the loop and not for the whole run.** The study needs the
populations inside each generation (parents, offspring and survivors), which pymoo's
`minimize` does not expose as such. We therefore own the loop and the data it emits, and
delegate the numerically delicate pieces to pymoo through adapters
(`operators/variation.py`, `operators/survival.py`): its vectorised SBX/PM kernels and its
compiled non-dominated sorting and NSGA-III normalisation/niching. Only the adapters import
pymoo. A slow test checks that both algorithms are statistically equivalent to pymoo's native
implementations on DTLZ2.

**Populations are structures of arrays** (`X` of shape `(n, n_var)`, `F` of shape `(n, n_obj)`,
plus per-individual attribute arrays such as `rank`). Object orientation lives at the level of
components, while every numerical step stays vectorised. Arrays are read-only, so the same
population can be handed to any number of observers safely.

### Observers: where analyses plug in

Everything that happens during a run is an `AlgorithmObserver`:

- `IndicatorObserver` computes IGD, IGD+ and hypervolume on the first front;
- `SnapshotObserver` writes generation snapshots to Parquet;
- `ProgressObserver` streams progress and the current front.

A persistent-homology analysis will be another observer receiving each `GenerationRecord`, with
no change to the algorithms.

### Generation snapshots

Each run has a directory `data/runs/<run-id>/` with `meta.json` and `part-*.parquet` files. Each
stored generation contributes one row per individual of `P_t ∪ Q_t`:

| column                  | meaning                                                 |
| ----------------------- | ------------------------------------------------------- |
| `generation`            | `t` (0 = initial population)                            |
| `role`                  | 0 = parent pool `P_t`, 1 = offspring `Q_t`              |
| `index`                 | position within its role                                |
| `survived`              | selected into `P_{t+1}`                                 |
| `rank`                  | non-domination rank in the survival (-1 if discarded)   |
| `times_selected`        | number of matings the parent took part in               |
| `parent_a`, `parent_b`  | indices into `P_t` (offspring rows)                     |
| `mutated`               | whether mutation changed the offspring                  |
| `x_0 … x_{n-1}`         | decision variables (optional)                           |
| `f_0 … f_{m-1}`         | objectives                                              |

Rows are buffered and flushed as zstd-compressed parts every few generations, so memory stays
bounded, and parts are renamed atomically so they can be read while the run is still going.
Storage is controlled per experiment (every N-th generation, `float32`, objectives only). For
example, NSGA-III on 3-objective DTLZ2 with 92 individuals, 250 generations, all variables in
`float64` takes about 3 MB per run on disk.

Reading a run in a notebook:

```python
import pyarrow.dataset as ds

table = ds.dataset("data/runs/<run-id>", format="parquet").to_table()
df = table.to_pandas()          # or polars.from_arrow(table)
gen = df[df.generation == 100]
```

### Execution, progress and cancellation

1. `POST /api/experiments` stores the experiment and one row per run (seeds derived with
   `numpy.random.SeedSequence`), then enqueues one RQ job per run.
2. A worker claims the run atomically (`queued → running`) and executes it. Metric rows are
   written in batches; progress (generation and current first front) is published on Redis at
   most every 250 ms and forwarded by the API to the browser over a WebSocket.
3. Cancellation is cooperative: the API sets a Redis flag that the worker checks at most every
   500 ms, so a cancelled run stops cleanly and keeps everything stored so far.

## Frontend

React + TypeScript (strict) + Vite, with Mantine for components, TanStack Query for server
state and Plotly for scientific charts (loaded lazily).

- API types are generated from the backend's OpenAPI document (`make openapi`), so the
  contract is checked at compile time.
- Configuration is validated by the server: the editor sends every change (debounced) to
  `POST /api/experiments/preview`, which returns derived quantities or field-level errors.
- Chart colours come from a palette validated for colour-vision deficiency in both themes.
  Identity is never colour alone (filled = survived, open = discarded; legends everywhere).

## Extending

**A new problem.** Subclass `core.Problem` (vectorised `_evaluate`), and implement
`KnownParetoFront` if the front is known (enables IGD/IGD+/HV). Add a config model in
`experiments/config.py`, turn `ProblemConfig` into a discriminated union on `name`, and
register a builder in `experiments/registry.py`.

**A new algorithm.** Compose `core.EvolutionaryAlgorithm` with existing or new strategies
(`MatingSelection`, `Crossover`, `Mutation`, `Survival`). Add its config model to the
`AlgorithmConfig` union and register a builder.

**A new analysis per generation.** Implement an `AlgorithmObserver` and add it in
`experiments/runner.py`. It receives every `GenerationRecord`.

After changing API models, run `make openapi` to regenerate the frontend types.

## Supply-chain policy

- Python dependencies are resolved by `uv` with `exclude-newer` (no release younger than the
  cut-off date) and locked with hashes (`backend/uv.lock`).
- npm dependencies were resolved with `npm install --before=<date>` and are installed with
  `npm ci` from the lockfile (`frontend/package-lock.json`, integrity hashes).
- Package names, maintainers and source repositories are verified on PyPI/npm before adding a
  dependency.
- Docker base images and GitHub Actions are pinned by digest/commit SHA.
