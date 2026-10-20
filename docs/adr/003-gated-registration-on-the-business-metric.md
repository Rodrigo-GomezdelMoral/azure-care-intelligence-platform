# ADR-003 · Registration is gated on the business metric

**Status:** accepted · **Date:** 2026-10-20

## Context

A training pipeline that registers whatever it produces turns the model registry into a log of
runs: every version is "the latest", and the question of whether any of them is better than
the one in production is answered later, by whoever happens to look. The specification asks for
the opposite: registration is earned by beating the current champion, and promotion to
production is a separate human decision (ADR-004).

The metric the gate compares has to be the one the buyer cares about. A medical director does
not ask for the AUC; they ask which patients to call this week and what it saves. The business
metric defined in `src/economics.py`, **cost avoided per thousand patients contacted** under the
programme's capacity, answers that question directly, and a model can improve its AUC while
getting worse at it (experiment 002 quantifies the gap between the two views).

## Decision

The `register` component reads the evaluation report of the test split and the registry:

1. The champion is the model version tagged `stage=champion`; the workspace registry supports
   neither MLflow aliases nor the deprecated stages API, so the tag is the mechanism (ADR-001).
   Its own `cost_avoided_per_thousand` tag is the number to beat, so the comparison never
   depends on re-evaluating an old model.
2. With no champion, the first evaluated model is registered as champion.
3. Otherwise the challenger is registered, tagged `stage=challenger`, only if its cost avoided
   per thousand contacts exceeds the champion's by `min_improvement` (default 0, in euros per
   thousand contacts). **Ties lose.** A model that is not measurably better has not earned a
   registration, and a pipeline rerun on the same data and parameters must not create a new
   version.
4. A refusal is not a failure: the step completes, logs the comparison (`decision`, `champion`,
   `challenger`, `champion_version`) to its run, and writes it to the `decision` output, which
   the staging workflow publishes on the pull request. Red pipelines are for broken code; "no
   better model today" is a result.

The decision is a pure function, `decide(incumbent, challenger, min_improvement)`, and
`tests/test_evaluation.py` proves the refusal both on the function and on the component
against a real (file-based) registry: the second registration of an identical model is refused
and the registry still holds one version.

## Consequences

- Every registered version carries the metrics it earned, the data asset version it was trained
  on and the pipeline run that produced it as tags, so a reviewer compares versions from the
  registry page alone.
- The gate compares numbers from the same test split only when the data asset version is the
  same. A new data asset version makes the champion's metric non-comparable; `min_improvement`
  can be raised to demand a margin, and the model card records which data version each
  registered model was evaluated on.
- The test split is small enough (6,000 patients, 120 contacts) that the metric has sampling
  noise of the order of tens of thousands of euros per thousand contacts. A margin of zero is
  therefore the right default for a demonstration, and a production programme would set
  `min_improvement` from a bootstrap of the test split before trusting a small gain.
- Fairness is reported, not gated, in this phase: the audit (`src/fairness.py`) is in the same
  evaluation report, and the model card quotes its worst disparity. Gating on it is a policy
  decision the programme owner takes, with experiment 003 as the evidence.

## Rejected

- **Register everything, promote by hand.** The registry stops meaning anything, and the person
  promoting has to redo the comparison the pipeline already made.
- **Gate on AUC or F1.** Discrimination can improve while the ranking at the capacity cut does
  not, and F1 optimises a threshold the programme never uses (ADR-005).
- **Fail the pipeline on refusal.** It conflates "the code broke" with "the model is not
  better", which are different pages in the runbook.
