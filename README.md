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

## Repository layout (proposed)

```
esphea/
├── docs/          # notes, literature review, paper drafts
├── src/           # implementation (EAs, PH computation, descriptors)
├── experiments/   # experiment configurations and scripts
├── notebooks/     # exploratory analyses
└── results/       # processed results and figures
```

## Planned tooling

Python, with TDA libraries such as [GUDHI](https://gudhi.inria.fr/), [Ripser](https://ripser.scikit-tda.org/), [giotto-tda](https://giotto-ai.github.io/gtda-docs/) and [persim](https://persim.scikit-tda.org/), and evolutionary computation libraries such as [DEAP](https://github.com/DEAP/deap) and [pymoo](https://pymoo.org/).

## Introductory references

- Edelsbrunner, H.; Harer, J. *Computational Topology: An Introduction*. American Mathematical Society, 2010.
- Carlsson, G. Topology and data. *Bulletin of the American Mathematical Society*, 46(2), 255–308, 2009.
- Otter, N. et al. A roadmap for the computation of persistent homology. *EPJ Data Science*, 6(17), 2017.
- Eiben, A. E.; Smith, J. E. *Introduction to Evolutionary Computing*. 2nd ed. Springer, 2015.

## License

This repository is dual-licensed, as is common for academic work:

- **Source code** (`src/`, `experiments/`, scripts and notebooks): [MIT](LICENSE).
- **Text, figures, data and results** (`docs/`, `results/` and other non-code material): [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-CC-BY-4.0).

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
