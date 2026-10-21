# ADR-001 · Four components and a pipeline, not one training script

**Status:** accepted · **Date:** 2026-10-20

## Context

A readmission model can be trained by one script that reads the cohort, fits a classifier,
prints a few metrics and registers the result. It is the first version of every machine-learning
project, and it is where most of them stop. The question for this repository is what the
training run has to be once people who did not write it operate it: reproducible from recorded
inputs, testable one stage at a time, resubmittable by a drift monitor, and reviewable at the
point where a model becomes a candidate for production.

## Decision

Training is four YAML-specified command components, each a Python module that runs standalone
against files, composed by an `@pipeline` job in `pipelines/training.py` on serverless compute:

| Component | Reads | Writes | Decision it owns |
|---|---|---|---|
| `prep` | the cohort data asset | train, validation and test splits | the schema is the contract; drift stops the run here |
| `train` | train and validation | an MLflow model | the model is one `Pipeline` with its preprocessing inside; validation metrics carry the names the sweep optimises |
| `evaluate` | model and test | `metrics.json` | the test split is touched once; the business metric is computed with the programme's parameters |
| `register` | model and `metrics.json` | a registry version | the first version is the champion, later ones are challengers; the gate (phase 5) and promotion (phase 9) read the same tags |

Each component's YAML declares typed inputs and outputs (`uri_file`, `mlflow_model`),
parameters with defaults, and an inline environment built from `src/components/conda.yml`, whose
pins are the ones in `requirements.txt`. `code: ../..` makes the repository root (minus
`.amlignore`) the snapshot, so the components share `src/economics.py` and `data/schema.json`
instead of copying them; Azure ML versions that snapshot by content hash, and the YAML `version`
is the declared contract.

Two placements differ from the specification's one-line description of `prep` ("validation,
imputation, encoding, split"). Imputation and the one-hot encoding of the nominal columns are
fitted on the training split, so they live inside the model's `ColumnTransformer`: the endpoint,
the explainer and the batch run then see raw columns and cannot disagree with training about how
a missing value was filled. And the validation split exists so that `train` can log the business
metric on data it did not fit, which is what makes the same component the trial of the sweep
without touching the test split.

MLflow is the only tracking and registry surface. Every component logs to its own step run,
children of the pipeline run; `register` logs the model again under its run and registers that
copy, so the registry version points at the pipeline that produced it, and the evaluation
metrics, the data asset version and the pipeline run are tags on the version. Two findings
measured on 2026-10-20 shaped this: the workspace's tracking backend answers 404 to MLflow 3's
logged-model and alias endpoints, and `azureml-mlflow` up to 1.62 declares `mlflow-skinny<=3.15`.
The repository therefore pins MLflow 2.22.5, and champion and challenger are the version tag
`stage`, not an alias and not the deprecated stage API.

## Consequences

- Each component runs locally with `python -m src.components.<name>` against parquet files and a
  local `mlruns/`, which is how its tests and its standalone check work; the pipeline is the only
  thing that needs a workspace.
- A pipeline run is four jobs, and serverless compute provisions a node for each, so the run
  takes longer than the arithmetic of its steps; `docs/cost.md` prices it and compares it with
  the persistent cluster that was rejected (ADR-002).
- The sweep (phase 6) wraps `train` unchanged, batch scoring (phase 7) loads the registered
  version, and the drift trigger (phase 8) resubmits this pipeline; none of them needs a new
  training path.
- Pipeline composition is tested offline: the four specs load, the nodes are wired, serverless is
  the default compute. Whether a component's command line matches its script is only proven by
  running it, which the dev workflow does on every push.

## Revisit when

A second team or a second model reuses these components: then they are registered as named versions in a shared registry, and the pipeline references them by version instead of by file.

## Rejected

- **One script.** Fastest to write, impossible to test by stage, and the sweep and the drift
  trigger would each have needed their own copy of its parts.
- **Python function components** (`@command_component`). Less to write, but the contract lives
  in decorators rather than in a file that CI validates and a reviewer reads without Python.
- **Registering named component versions on every run.** Component versions are immutable, so
  every edit would have needed a version bump before a dev run; anonymous versions by content
  hash are what development needs, and naming them is a release-time decision for phase 9.
- **Registering from `train` directly.** It saves a step, but it registers a model nobody has
  evaluated, which is the opposite of the gate this repository exists to demonstrate.
