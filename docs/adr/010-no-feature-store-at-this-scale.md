# ADR-010 · Rejected: a feature store at this scale

**Status:** accepted · **Date:** 2026-10-21

## Context

Feature stores, including Azure Machine Learning's managed feature store, solve real problems:
features shared across many models and teams, point-in-time correct joins over event history, and
the same feature computed identically for training and serving.

## Options

1. **A managed feature store** with feature sets for the cohort.
2. **One versioned data asset plus a schema contract**, with the transformations inside the model.

## Decision

**Option 2.** There is one model, one team and one table. The cohort is a versioned data asset
whose hash is in its tags; `data/schema.json` is the contract `prep` enforces; and imputation and
encoding are fitted inside the scikit-learn pipeline, so training, the online endpoint, the batch
endpoint and the explainer all see the same transformation by construction (ADR-001). The problem
a feature store solves for serving skew is already solved by shipping the preprocessing inside the
model.

## Consequences

- No feature definitions to register, no materialisation jobs, no offline and online stores to pay
  for and keep in sync.
- A second model that wanted the same features would have to read the same asset, which is
  acceptable at two models and not at twenty.

## Revisit when

A second team or a second model needs the same features, or the features become time-dependent
aggregates over event history that need point-in-time correctness.

## Rejected

- **A managed feature store now.** Infrastructure, cost and concepts for a problem this system does
  not have.
