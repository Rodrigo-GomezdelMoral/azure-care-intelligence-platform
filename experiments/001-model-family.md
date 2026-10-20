# Experiment 001 · Logistic regression versus gradient boosting

**Date:** 2026-10-20 · **Data asset:** `patient-cohort:1` (40,000 synthetic patients, 57 features) ·
**Runs:** `red_collar_g75j7w4dyp` (gradient boosting, champion v1) and `amusing_king_3524wpr8hz` (logistic regression) ·
**Split:** 70/15/15 stratified, seed 7

## Hypothesis

Gradient boosting beats a regularised logistic regression on discrimination and on the business
metric by enough to justify its inference cost and its opacity. If it does not, the simpler
model should be the champion.

## Variants

Both are the same scikit-learn `Pipeline` (median imputation, one-hot encoding of the four
nominal columns, see ADR-001) with a different last step, selected by the `family` input of the
`train` component:

| Variant | Last step | Parameters |
|---|---|---|
| `gradient_boosting` | `HistGradientBoostingClassifier` | learning rate 0.05, 300 iterations, 31 leaves, 20 samples per leaf, no L2 (the `train` defaults) |
| `logistic_regression` | `StandardScaler` + `LogisticRegression` | C = 1.0, 2,000 iterations |

## Method

One run of the training pipeline per variant on serverless compute, `--family` being the only
difference (`make pipeline` and `python -m pipelines.training --family logistic_regression`).
Discrimination and calibration are the `evaluate` metrics on the untouched test split (6,000
patients); the business metric is cost avoided per thousand contacts with the top 2 % contacted
(120 patients, ADR-005). Inference cost was measured locally on the same test split with the
models each pipeline produced: five batch calls of 6,000 rows and fifty single-row calls, median
of the means.

## Results

| | Gradient boosting (champion v1) | Logistic regression |
|---|---|---|
| AUC | 0.756 | 0.757 |
| Average precision | 0.459 | 0.465 |
| Brier score | 0.129 | 0.128 |
| Expected calibration error (10 bins) | 0.014 | 0.018 |
| Precision among the 120 contacted | 0.758 | 0.750 |
| **Cost avoided per thousand contacts** | **875,000 €** | **865,000 €** |
| Validation AUC (the sweep's view) | 0.754 | 0.753 |
| Batch inference, 1,000 rows | 2.4 ms | 1.9 ms |
| Single-row call | 5.3 ms | 2.9 ms |
| Serialised model | 262 KB | 7 KB |

The 10,000 € gap on the business metric is one readmitted patient among 120 contacts
(0.25 × 4,800 € × 1,000 / 120 = 10,000 €): inside the sampling noise of the test split.

## Decision

**The simpler model is as good on this cohort, and the experiment says so.** The reason is in
ADR-008: the generator draws the label from a logistic equation of the features, so a logistic
regression is the true model family here and gradient boosting cannot find interactions that do
not exist. The result is a property of the synthetic data, not evidence about chronic-care
cohorts, where non-linear effects (adherence falling off a cliff past a drug count, age by
comorbidity interactions) are the normal case.

The repository keeps **gradient boosting as the champion family**, for two stated reasons:

1. The serving path (phase 7) explains every score with SHAP tree values, the sweep (this
   phase) and the drift story are built for the family a real cohort needs, and the point of the
   repository is that lifecycle; switching the family to fit a synthetic artefact would make the
   demonstration less transferable, not more honest.
2. The gate (ADR-003) already encodes the rule the hypothesis asked for: when the two are tied
   on the business metric, the incumbent stays. The logistic regression run was refused by
   `register` for that reason, and the refusal is in its run.

What the result changes: the model card states that on this data a logistic regression is an
equally good and cheaper choice, and a real deployment should rerun this experiment on its own
extract before accepting the boosted model's inference and explanation cost.
