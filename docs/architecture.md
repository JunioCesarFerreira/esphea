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
| `watchdog` | Recovers runs whose worker died (expired lease) or whose job Redis lost.      |
| `migrate`  | One-shot Alembic migration before the API and workers start.                   |

Backend containers start as root only long enough to adopt the owner of the mounted `./data`
directory, then drop privileges to that user (`backend/docker-entrypoint.sh`). Files written by
the workers therefore belong to the host user with no configuration.
| `postgres` | Experiment metadata, run status and per-generation indicator values.           |
| `redis`    | Job queue (RQ), live events (pub/sub) and cooperative cancellation flags.     |

## Backend layers

The backend (`backend/src/esphea`) is layered so that inner layers never import outer ones:

```
core            domain: Problem, Population, operator interfaces, the evolutionary loop
topology        persistent homology: point clouds, Vietoris-Rips, diagram distances, analyses
problems        benchmark problems (DTLZ2, DTLZ2-H, DTLZ7, ZDT1, ZDT3, ZDT4)
operators       concrete strategies (sampling, selection, SBX, PM, survival)
algorithms      NSGA-II, NSGA-III and SMS-EMOA as compositions of strategies
metrics         quality indicators (IGD, IGD+, GD, hypervolume) and diversity metrics
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

NSGA-II, NSGA-III and SMS-EMOA are the same loop with different strategies:

|                  | NSGA-II                         | NSGA-III                                      | SMS-EMOA                       |
| ---------------- | ------------------------------- | --------------------------------------------- | ------------------------------ |
| Mating selection | binary tournament (rank, crowding) | random                                     | random                         |
| Crossover        | SBX, η = 15, p = 0.9            | SBX, η = 30, p = 1                            | SBX, η = 15, p = 0.9           |
| Mutation         | polynomial, η = 20, p = 1/n     | polynomial, η = 20, p = 1/n                   | polynomial, η = 20, p = 1/n    |
| Survival         | non-dominated sorting + crowding distance | non-dominated sorting + reference-point niching | non-dominated sorting + least hypervolume contribution, removed one at a time |
| Population       | user defined                    | smallest multiple of 4 ≥ number of Das–Dennis directions | user defined |

SMS-EMOA is originally steady state (one offspring per iteration). Here it produces a whole
generation of offspring and then removes the least contributors of `P_t + Q_t` one by one, so its
generations line up with those of the NSGA variants (and with the zigzag `P_t -> R_t <- P_{t+1}`).

**Why pymoo is used for parts of the loop and not for the whole run.** The study needs the
populations inside each generation (parents, offspring and survivors), which pymoo's
`minimize` does not expose as such. We therefore own the loop and the data it emits, and
delegate the numerically delicate pieces to pymoo through adapters
(`operators/variation.py`, `operators/survival.py`): its vectorised SBX/PM kernels and its
compiled non-dominated sorting, NSGA-III normalisation/niching and SMS-EMOA hypervolume
contributions. Only the adapters import
pymoo. A slow test checks that NSGA-II and NSGA-III are statistically equivalent to pymoo's native
implementations on DTLZ2.

**Populations are structures of arrays** (`X` of shape `(n, n_var)`, `F` of shape `(n, n_obj)`,
plus per-individual attribute arrays such as `rank`). Object orientation lives at the level of
components, while every numerical step stays vectorised. Arrays are read-only, so the same
population can be handed to any number of observers safely.

### Observers: where analyses plug in

Everything that happens during a run is an `AlgorithmObserver`:

- `IndicatorObserver` computes IGD, IGD+, GD and hypervolume on the first front of the
  survivors, and the hypervolume of the offspring `Q_t` that produced the generation
  (`hv_offspring`, from generation 1 on, same reference point); it also computes the
  diversity metrics (`spacing` and `spread` on the first front, `mean_distance` on the
  survivors, all with objectives scaled by the ideal and nadir points, and
  `decision_inertia` on the variables scaled by the bounds), storing a value only where it is
  defined (e.g. at least two points);
- `SnapshotObserver` writes generation snapshots to Parquet;
- `ProgressObserver` streams progress and the current front.

A persistent-homology analysis will be another observer receiving each `GenerationRecord`, with
no change to the algorithms.

### Generation snapshots

Each execution attempt of a run has a directory `data/runs/<run-id>/attempt-<n>/` with
`meta.json` and `part-*.parquet` files (normally only `attempt-1`; see *Recovery* below). Each
stored generation contributes one row per individual of `P_t ∪ Q_t`:

| column                  | meaning                                                 |
| ----------------------- | ------------------------------------------------------- |
| `generation`            | `t` (0 = initial population)                            |
| `individual_id`         | run-unique identity of the individual (schema 2)        |
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

table = ds.dataset("data/runs/<run-id>/attempt-1", format="parquet").to_table()
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

### Recovery of lost workers

A worker that dies in the middle of a run (crash, OOM, container killed) cannot report it, so
ownership of a run is a **lease** held by an **attempt**:

- Claiming a queued run starts attempt *n* (`attempt` column) and sets `heartbeat_at`. A thread
  in the worker renews the heartbeat every 5 s, independently of how long a generation takes.
- The `watchdog` service sweeps every 10 s. A running run whose heartbeat is older than 60 s
  lost its worker: its partial metrics and snapshots are discarded and it is queued again as
  attempt *n + 1* (seeds are fixed, so the retry is reproducible). After 3 attempts the run is
  marked failed. A queued run whose job is missing from Redis (e.g. after a Redis restart) is
  simply enqueued again.
- **Fencing:** every write of a worker (metrics, progress, final status) only applies while the
  run is still owned by its attempt, and snapshots go to a per-attempt directory. A worker that
  was merely cut off also stops by itself after 30 s without a successful heartbeat, before the
  watchdog can hand the run over. A late or "zombie" worker therefore can never corrupt the retry.

Timings are configurable (`ESPHEA_HEARTBEAT_INTERVAL_SECONDS`, `ESPHEA_LEASE_TIMEOUT_SECONDS`,
`ESPHEA_MAX_RUN_ATTEMPTS`, `ESPHEA_WATCHDOG_INTERVAL_SECONDS`, `ESPHEA_ENQUEUE_GRACE_SECONDS`).

## Persistent-homology analyses

Analyses are computed **offline** from the stored generations of a finished run, so the same run
can be analysed with different parameters without re-running the algorithm. They are leased jobs
like runs (same queue, heartbeats, fencing and watchdog recovery).

For every stored generation `g` an analysis computes:

1. the **point cloud** in objective space: the survivors `P_g` (default), the candidates
   `P_{g-1} ∪ Q_{g-1}` or the first front of `P_g`;
2. an optional **normalisation**: none (default), fixed (ideal → 0, nadir → 1, the same map for
   every generation) or min–max per generation (shape without scale);
3. the **Vietoris–Rips** persistence diagram (Ripser) of `H_0 … H_k` (k ≤ 2), with ε the
   maximum *edge length*, from 0 to the configurable `max_epsilon`. Features still alive at
   `max_epsilon` (always including the essential class of `H_0`) are truncated there, which keeps
   all distances finite; diagrams are only comparable for the same `max_epsilon`;
4. **distances between diagrams** (GUDHI: exact bottleneck and Wasserstein W₁ with the L∞ ground
   metric), per dimension, to the previous stored generation and to the final one, plus the
   **Hausdorff distance** between the clouds as the baseline of the stability theorem
   (`d_B(D(X), D(Y)) ≤ 2·d_H(X, Y)`);
5. summaries (number of bars, total persistence, persistent entropy) and, on request, the
   pairwise distance matrix of up to 100 generations.

Results live in `data/runs/<run-id>/analyses/<analysis-id>/attempt-<n>/` (`diagrams.parquet`,
`series.parquet`, `clouds.parquet`, optional `matrix.parquet`, `meta.json`). Betti curves are
derived from the diagrams on request. `GET /api/runs/{id}/epsilon-suggestion` reports the cloud
diameters and nearest-neighbour spacing of the run to help choosing `max_epsilon` (the suggested
value is the largest diameter, so every finite feature is captured).

Note on `H_0`: populations may contain identical individuals (clones), which merge at ε = 0;
β₀(0) therefore counts *distinct* points.

### Zigzag persistence across generations

A zigzag analysis follows the topology of the population *through* the evolution, along the
sequence of inclusions

```
P_0 → R_1 ← P_1 → R_2 ← P_2 → … ← P_T,      R_t = P_{t-1} ∪ Q_t
```

numbered by steps (`P_t` is step `2t`, `R_t` step `2t − 1`). Every set is replaced by its
Vietoris–Rips complex at a **fixed scale ε** (up to five scales per analysis, H₀ … H₂).
Individuals keep their identity along the sequence (the `individual_id` of the snapshots, so
runs stored before schema 2 cannot be zigzagged, and every generation must be stored).

A bar is alive on steps `[birth, death − 1]`. Forward arrows only insert simplices (offspring)
and backward arrows only remove them (discarded individuals), so every event has a cause:

| event | on a forward arrow `P_{t-1} → R_t` | on a backward arrow `R_t ← P_t` |
|---|---|---|
| birth | **variation**: e.g. offspring found a new niche | **selection**: e.g. removing a bridge splits a niche |
| death | **variation**: e.g. offspring bridge two niches | **selection**: e.g. a niche is wiped out |

The barcode is computed with Dionysus' fast zigzag (Dey and Hou), which reduces the zigzag to
the extended persistence of a cone. Tests check, on random sequences, that the number of bars
alive at every step equals the Betti numbers computed independently by Ripser, and the API
reports identities such as `β(R_t) = β(P_{t-1}) + births_var(t) − deaths_var(t)`.

**Representatives.** For the longest bars, the representative cycle at each step is stored
(as individual ids); for H₀ the API expands it to the ε-connected niche. Keeping the matrix
needed for representatives is far more expensive than the barcode (0.8 M simplices: ~60 s and
2.4 GB, against ~5 s), so representatives are only extracted up to 500 000 simplices per scale;
above that the scale records why they were skipped. Representatives of intervals of type
"open at birth, closed at death" are sometimes unavailable (a Dionysus limitation) and are
reported as such.

**Cost and memory.** Each scale is limited to 3 M simplices (about 1–2 GB). Suggested scales are
1, 1.5 and 2 × the median nearest-neighbour spacing of the *population* `P_t` (the spacing of
`R_t` is dominated by offspring next to their parents and would isolate every individual).

**Batches.** The same analysis can be queued for every finished run of an experiment; the batch
summary gives the median and quartiles across runs of the Betti numbers and of births and deaths
by cause, per generation.

**Niche trackers.** At every scale the zigzag analysis also follows the H₀ niches with three
heuristic trackers (`esphea.topology.trackers`), stored as `trackers.parquet` (zigzag results
schema 2). They see the same niches as the zigzag and differ only in how they link them over
time:

| tracker | sees | rule |
|---|---|---|
| `t1` | every `P_t` and `R_t` | elder rule at merges, largest fragment keeps the bar at splits (tracking graphs) |
| `t1o` | every `P_t` and `R_t` | as `t1`, but the fragment holding the oldest individual keeps the bar |
| `t2` | the populations `P_t` only | components matched through shared survivors, as cluster and community trackers do |

The comparison reports, per method, the number of bars, the long bars (alive at least
`long_lifetime` steps), lifetime quantiles and the share of the zigzag bars a tracker reproduces,
matched by step or by generation. Matching by generation counts `R_t` and `P_t` as generation `t`,
which removes the one-step offset of `t2`: it never sees `R_t`, so it dates births by offspring and
merges through offspring at `P_t`. Endpoints: `GET /api/analyses/{id}/zigzag/trackers/{method}/bars`,
`.../zigzag/trackers/comparison`, `GET /api/analysis-batches/{id}/tracker-comparison` and
`GET /api/experiments/{id}/analysis-groups/{key}/tracker-comparison` (per-run values). Results
written before the trackers existed answer 404 and are skipped in batches and groups; running the
analysis again computes them.

**Groups and comparison.** `GET /api/experiments/{id}/analysis-groups` groups an experiment's
analyses (either kind) by configuration, keeping the newest completed analysis of each run.
Settings that only change what is stored (`distance_matrix`, `representatives`) are left out of
the group key, which is a hash of the configuration alone: the same configuration has the same
key in every experiment. `GET .../analysis-groups/{key}/summary` gives, per generation, the
median and quartiles across runs of every summarised series (barcode summaries and distances, or
zigzag Betti numbers and events), plus the spread of the per-run totals of the zigzag events.
The *Compare* page uses them to set experiments side by side: it picks by default the
configuration shared by most selected experiments, warns when the compared analyses differ in
normalisation, point cloud or scale, and can queue the same configuration for the experiments
that lack it. Summaries are only comparable within one scale and one objective space, so a fixed
normalisation (`ideal_nadir`) and equal ε are the meaningful setting across experiments.

Analyses run in a **supervised child process** (`spawn`): native code such as Dionysus holds
the GIL for long stretches, so the parent process keeps the lease heartbeat alive, relays
progress and terminates the child if the lease is lost.

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
`KnownParetoFront` if the front is known (enables IGD/IGD+/GD/HV). Add a config model in
`experiments/config.py` to the `ProblemConfig` discriminated union (on `name`), register a
builder in `experiments/registry.py` and list its defaults in the API catalog. The ZDT
problems (`problems/zdt.py`) show the pattern for a family: a base class holds the shared
structure `f_2 = g * h` and extracts the front numerically, so each member only defines `g`
and `h`.

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
