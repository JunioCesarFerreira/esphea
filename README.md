# ESPHEA

**E**xploratory **S**tudy of **P**ersistent **H**omology in **E**volutionary **A**lgorithms

> ⚠️ **Status:** early-stage research. Hypotheses, methods and repository layout are subject to change.

## Motivation

Evolutionary algorithms (EAs) operate on populations of candidate solutions that move through search spaces which are often high-dimensional, multimodal and poorly understood. Classical diversity measures (mean pairwise distance, entropy, genotypic variance) collapse the population into a single number and lose information about its **shape**: how many clusters exist, whether there are "holes" or cyclic structures, and how these structures appear and vanish over the generations.

**Persistent homology** (PH), a central tool of Topological Data Analysis (TDA), describes the shape of point clouds across multiple scales through topological invariants (connected components, loops, voids) and their persistence along a filtration. This repository investigates whether this multiscale description can provide a new and useful view of EA dynamics.

## Research questions

1. **Population characterization:** do persistence diagrams of the population capture diversity and niche structure better than classical metrics?
2. **Dynamics monitoring:** can premature convergence, stagnation or loss of diversity be detected from topological signatures over the generations?
3. **Fitness landscape analysis:** does PH applied to landscape samples (or to fitness-based sublevel filtrations) reveal information about problem modality and difficulty?
4. **Adaptive control:** can topological descriptors be used as a feedback signal to tune operators and parameters (mutation rate, selection pressure, niching, restarts)?
5. **Multi-objective optimization:** can the topology of Pareto front approximations serve as a quality or coverage indicator?

## Planned approach

- **Representation:** the population at each generation is treated as a point cloud in genotype and/or phenotype space (or in objective space).
- **Filtrations:** Vietoris–Rips and Alpha complexes, and sublevel-set filtrations of the fitness function.
- **Descriptors:** persistence diagrams, barcodes, persistent entropy, persistence landscapes and images, and *bottleneck* / *Wasserstein* distances between generations.
- **Algorithms:** Genetic Algorithms, Evolution Strategies (incl. CMA-ES), Differential Evolution and multi-objective EAs (e.g. NSGA-II).
- **Test problems:** continuous benchmark functions (e.g. the BBOB/COCO suite, Rastrigin, Schwefel), combinatorial problems and multi-objective problems (ZDT, DTLZ).
- **Evaluation:** comparison against classical diversity and performance metrics, with multiple independent runs and appropriate statistical tests.

## Current status

The first milestone is an experimentation platform for **NSGA-II** and **NSGA-III** on the
scalable **DTLZ2** benchmark and the bi-objective **ZDT1**, **ZDT3** (disconnected front) and
**ZDT4** (multimodal) benchmarks, built so that persistent homology can be applied to the
populations *inside* each generation:

- own generational loop exposing, at every generation, the parent pool `P_t`, the matings, the
  offspring `Q_t` with their lineage and mutation flags, and the survivors `P_{t+1}`, while the
  numerical kernels (SBX, polynomial mutation, non-dominated sorting, NSGA-III niching) come from
  [pymoo](https://pymoo.org/), validated statistically against pymoo's native algorithms;
- quality indicators (IGD, IGD+, hypervolume) from [moocore](https://multi-objective.github.io/moocore/python/), and GD (nearest reference point via a SciPy KD-tree);
- every stored generation persisted as compressed Parquet, ready for notebooks;
- a web interface to configure experiments, follow runs live, replay generations in objective
  space (2D, 3D or parallel coordinates) and compare convergence across experiments;
- **persistent homology** of the population at every generation: Vietoris–Rips barcodes in
  objective space up to a configurable ε, bottleneck/Wasserstein distances between generations
  (with the Hausdorff stability bound), Betti curves and summaries, computed offline from the
  stored generations and explored in the *Topology* tab;
- **zigzag persistence** of P₀ → R₁ ← P₁ → … at fixed scales: niches and loops followed across
  generations, every birth and death attributed to variation (offspring) or selection (removal),
  representative niches/cycles in objective space and across-run summaries.

See [docs/architecture.md](docs/architecture.md) for the design and how to extend it.

## Getting started

Requirements: Docker (with Compose). Nothing else needs to be installed on the host.

```bash
make up          # or: docker compose up -d --build
```

- Web interface: <http://localhost:8090>
- API documentation: <http://localhost:8000/api/docs>
- Generation snapshots: `./data/runs/<run-id>/attempt-<n>/*.parquet`

Ports can be changed with `ESPHEA_UI_PORT` and `ESPHEA_API_PORT`; parallel workers with
`ESPHEA_WORKERS` (default 2) or `docker compose up --scale worker=N`.

### Development

```bash
make help               # list all shortcuts
make check              # backend (ruff, mypy, pytest) and frontend (eslint, tsc, vitest, build)
make backend-validate   # slow statistical comparison with pymoo's NSGA-II/NSGA-III
make openapi            # regenerate the frontend API types after changing the API
```

## Repository layout

```
esphea/
├── backend/            # Python package `esphea` (algorithms, experiments, API, worker)
│   ├── src/esphea/
│   ├── tests/
│   └── migrations/     # Alembic
├── frontend/           # React + TypeScript web interface
├── docs/               # architecture, notes, literature review, paper drafts
├── data/               # experiment outputs (git-ignored)
└── docker-compose.yml
```

## Tooling

Backend: Python 3.13, NumPy, pymoo, moocore, PyArrow, FastAPI, SQLAlchemy, PostgreSQL,
Redis and RQ. Frontend: React, TypeScript, Vite, Mantine, TanStack Query and Plotly.
Persistent homology will use TDA libraries such as [GUDHI](https://gudhi.inria.fr/),
[Ripser](https://ripser.scikit-tda.org/), [giotto-tda](https://giotto-ai.github.io/gtda-docs/)
and [persim](https://persim.scikit-tda.org/).

## Introductory references

- Edelsbrunner, H.; Harer, J. *Computational Topology: An Introduction*. American Mathematical Society, 2010.
- Carlsson, G. Topology and data. *Bulletin of the American Mathematical Society*, 46(2), 255–308, 2009.
- Otter, N. et al. A roadmap for the computation of persistent homology. *EPJ Data Science*, 6(17), 2017.
- Eiben, A. E.; Smith, J. E. *Introduction to Evolutionary Computing*. 2nd ed. Springer, 2015.
- Deb, K.; Pratap, A.; Agarwal, S.; Meyarivan, T. A fast and elitist multiobjective genetic algorithm: NSGA-II. *IEEE Transactions on Evolutionary Computation*, 6(2), 182–197, 2002.
- Deb, K.; Jain, H. An evolutionary many-objective optimization algorithm using reference-point-based nondominated sorting approach, Part I. *IEEE Transactions on Evolutionary Computation*, 18(4), 577–601, 2014.
- Deb, K.; Thiele, L.; Laumanns, M.; Zitzler, E. Scalable test problems for evolutionary multiobjective optimization. In: *Evolutionary Multiobjective Optimization*, Springer, 105–145, 2005.

## License

This repository is dual-licensed, as is common for academic work:

- **Source code** (`backend/`, `frontend/`, scripts and notebooks): [MIT](LICENSE).
- **Text, figures, data and results** (`docs/`, experiment outputs and other non-code material): [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CC-BY-4.0).

Both allow broad reuse, provided that **authorship is properly attributed**.

## How to cite

If this work is useful for your research, please cite it. Citation metadata is provided in [`CITATION.cff`](CITATION.cff) (GitHub automatically shows a *"Cite this repository"* option).

```bibtex
@misc{ferreira2026esphea,
  author       = {Ferreira, Junio Cesar},
  title        = {{ESPHEA}: Exploratory Study of Persistent Homology in Evolutionary Algorithms},
  year         = {2026},
  howpublished = {\url{https://github.com/JunioCesarFerreira/esphea}}
}
```

## Author

**Junio Cesar Ferreira** — [@JunioCesarFerreira](https://github.com/JunioCesarFerreira)
