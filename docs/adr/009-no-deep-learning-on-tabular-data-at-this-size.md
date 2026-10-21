# ADR-009 · Rejected: deep learning on tabular data at this size

**Status:** accepted · **Date:** 2026-10-21

## Context

The cohort is 40,000 patients with 57 tabular features, a quarter of them binary. A neural
network, a tabular transformer or an MLP with embeddings, is the fashionable choice, and it would
look more advanced in a portfolio.

## Options

1. **Gradient-boosted trees**, `HistGradientBoostingClassifier`.
2. **A regularised logistic regression.**
3. **A neural network** for tabular data.

## Decision

**Options 1 and 2 are compared (experiment 001); option 3 is rejected.** The evidence:

- **Measured here.** On the test split the logistic regression and gradient boosting tie on every
  metric that matters, AUC 0.757 against 0.756 and 865,000 € against 875,000 € avoided per thousand
  contacts. When the simplest model already matches the boosted one, a deeper model has nothing
  left to find in this signal, and its cost would be paid in training time, tuning and
  explanation.
- **Published.** On medium-sized tabular benchmarks, tree-based models outperform deep networks
  and are far cheaper to tune (Grinsztajn, Oyallon and Varoquaux, *Why do tree-based models still
  outperform deep learning on tabular data?*, NeurIPS 2022, Datasets and Benchmarks track).
- **Required by the product.** Every score carries SHAP contributions computed exactly and quickly
  by `TreeExplainer` on the boosted model; a network would need approximate explainers whose
  output varies between calls, against ADR-012.

## Consequences

- Training takes under a minute per run on one CPU node, and the sweep explores the boosted
  model's space in twelve trials.
- The repository does not demonstrate deep learning, on purpose. The rest of the portfolio covers
  generative models.

## Revisit when

The data changes kind rather than size: free-text clinical notes, longitudinal event sequences or
images would justify a neural model, and the experiment template of 001 is where it would have to
earn its place.

## Rejected

- **A tabular transformer or MLP.** More parameters than the signal needs, slower to tune, and
  explanations that are approximations, for no measured gain.
