# ADR-007 · Drift triggers retraining, never promotion

**Status:** accepted · **Date:** 2026-10-21

## Context

The cohort the model scores changes: a new extract each week, a new prescribing pattern, a coding
change, a different population after a contract is won or lost. A model trained on last year's
cohort keeps ranking this year's without complaint, so the system needs to notice when the input
has moved and to retrain on the new data.

The tempting completion of that loop is automatic: detect drift, retrain, register, promote. It is
also how models fail silently. A retrain on a corrupted or shifted extract can produce a model that
wins on its own test split, which comes from the same shifted data, while being worse for the
patients the programme actually serves. Someone has to read the comparison before a care team
starts calling a different list.

## Options

1. **The managed Azure Machine Learning model monitor**, a `MonitorSchedule` with a
   `DataDriftSignal` run on serverless Spark.
2. **evidently in a scheduled workflow**, comparing data asset versions.
3. **No drift detection**, retraining on a fixed schedule.

## Decision

**Option 2.** `src/monitoring/drift.py` compares the data asset version the champion was trained on,
read from its `data_asset` tag, with the latest version of the same asset. evidently tests every
one of the 57 features with its default for the column type and sample size, which at this
cohort's size is Wasserstein or Jensen-Shannon distance, and the cohort has drifted when **30 % of
the features** have. `drift-check.yml` runs it on a schedule. On drift it opens a GitHub issue
listing the drifted features, which is the alert, and submits the training pipeline on the
current version.

That pipeline ends where every training run ends: at the registration gate (ADR-003). A better
model is registered as a **challenger**; a worse one is refused. Promotion to champion and any
change of endpoint traffic happen only in `deploy-prod.yml`, behind a GitHub Environment with a
named reviewer (ADR-004). `drift.py` contains no call that writes the registry stage or endpoint
traffic, and a test asserts it.

The managed monitor was not set aside for regional availability, which was not tested. It was set
aside because it is built around a timestamped production stream: the data collector of an online
endpoint, or a table with a timestamp column read through a lookback window, processed on
serverless Spark. This system's production path is a weekly batch over versioned data assets with
no timestamp, and the online endpoint is switched off between demonstrations for cost, so there is
no stream to collect. Comparing asset versions is the natural unit here, and evidently does it
deterministically, in the workflow, with the same identity as the rest of CI.

## Consequences

- Retraining runs only when the cohort moves, and every drift event leaves an issue with the
  evidence and a pipeline run with the comparison.
- The threshold trades sensitivity for noise. Two draws of the same population flag a few
  features through sampling alone, which a unit test checks; 30 % of the features means a broad
  shift, the kind a new extract or a population change produces. A single column that disappears,
  changes type or arrives mostly empty is caught earlier and harder by `prep`'s schema contract.
- The alert for drift is the GitHub issue, not an Azure Monitor rule, because the signal is
  computed outside Azure. A retraining run that fails still fires the pipeline-failure alert.
- Outcome monitoring, comparing predicted with realised readmissions among contacted patients, is
  not implemented: the label arrives thirty days after the contact and needs an outcome feed this
  repository does not have.

## Revisit when

Production scoring becomes a stream with data collection enabled, or extracts start carrying a
timestamp: then the managed monitor with the same threshold replaces this module. Revisit the
threshold after the first real drift events, with the issues as evidence.

## Rejected

- **Self-promotion after retraining.** It removes the only point where a person reads the
  comparison, and the failure it invites stays invisible until the outcomes arrive.
- **Retraining on a fixed schedule without detection.** It spends compute when nothing has changed
  and gives no evidence when something has.
- **A per-feature alert.** At 57 features it pages on noise; the schema contract handles the
  structural single-column failures.
