# ADR-008 · Synthetic data generation, and what it cannot show

**Status:** accepted · **Date:** 2026-10-20

## Context

The product is a readmission-risk model for chronic-care cohorts. A public portfolio cannot hold
a real cohort: patient data is personal data of the highest category, de-identification of a
sixty-feature tabular record is not a guarantee of anonymity, and no agreement exists that would
let a real extract be published. The alternatives were a public benchmark dataset (none covers
adherence, contact history and socioeconomic proxies together, and the well-known ones are small
and over-studied), or a synthetic cohort whose generation is itself part of the repository.

A synthetic cohort has one risk that matters more than realism: **a model can only find signal
that the generator put there.** Pure noise with a label drawn at random would make every
downstream number meaningless, and a label computed deterministically from the features would
make every model look perfect.

## Decision

`src/data/synthesize.py` generates the cohort as a two-layer causal structure, seeded (`SEED = 7`):

1. **A seed population** of 8,000 patients is drawn from parametric distributions chosen from the
   published literature on chronic-disease adherence, one feature per line in causal order: a mean
   proportion of days covered around 0.7, adherence falling with polypharmacy (five or more drugs),
   deprivation, depression, copays, living alone and a language barrier, and rising with a
   caregiver and care-manager contact; a 30-day readmission rate around 16–19 % that rises with
   non-adherence, comorbidity burden (a Charlson-like index), a prior admission, age, deprivation
   and heart failure, and falls with a caregiver. Measurements (HbA1c, blood pressure, LDL, eGFR,
   BMI) depend on the conditions.
2. **CTGAN** (SDV 2.0) is fitted on the seed's **root layer** — the seven variables without a
   parent in the graph: sex, age, urbanicity, deprivation, language barrier, employment and
   insurance — and samples 40,000 rows of it under **conditions that impose the documented
   categorical marginals** (`sdv.sampling.Condition`). Every variable with a parent — household,
   conditions, prescriptions, adherence, contacts, measurements — and the **label** are then
   computed by the same equations on the sampled roots, with Bernoulli noise. The signal is
   guaranteed to be there, and it is guaranteed not to be deterministic.

Clinical columns carry OMOP Common Data Model names — `person_id`, `gender_concept_id` (8507 and
8532), `condition_*`, `drug_era_count`, `visit_occurrence_count_12m`, `measurement_*` — so a
health-data reviewer recognises the shape at a glance. `data/schema.json` records every column's
type and role (demographic, socioeconomic, comorbidity, prescription, contact, measurement,
outcome) and is what `prep` validates incoming data against. `ops/data_asset.py` registers the
parquet file as the versioned data asset `patient-cohort`, tagged with its row count, SHA-256,
generator and seed, so every training run names the exact file it used.

`tests/test_synthesize.py` asserts the shape (57 features, no free text, no missing values) and
the structure (non-adherent patients readmitted more than twice as often as adherent ones, a
monotonic Charlson gradient, polypharmacy lowering adherence) on the seed alone, without torch,
so CI never fits a GAN.

### Why the two layers: what was measured on 2026-10-20

The first design fitted CTGAN on all 57 features and redrew only the label. It kept the label
gradients (because they are redrawn) and lost nearly everything else: with an 8,000-row seed and
30 or 150 epochs the correlation between drug count and Charlson index fell from about 0.5 to
0.01, HbA1c was identical for diabetic and non-diabetic patients, polypharmacy no longer lowered
adherence, and the female share moved from 0.52 in the seed to 0.38 and then 0.73 between runs.

Restricting CTGAN to the root layer restored every dependent relationship exactly (the equations
compute them), but plain sampling still drifted on low-cardinality categoricals — female share
0.39 to 0.67 across seeds of 8,000 and 40,000 rows and 100 to 300 epochs, language barrier 0.13
to 0.23 against 0.08 — a known weakness of CTGAN with small categorical columns. Conditional
sampling fixes it: the categorical roots are independent by construction in the seed, so one
condition per combination of their levels, sized by the product of the marginals (108
conditions), reproduces them exactly (female share 0.519, language barrier 0.079, urbanicity
0.25/0.45/0.30 in the published cohort), and CTGAN contributes the continuous roots — age
67.9 ± 11.8 against 67.1 ± 10.9 in the seed, deprivation 4.34 against 3.99. The published cohort
has a readmission rate of 0.189 and a mean PDC of 0.675. Generation takes under three minutes on
a laptop CPU (100 epochs).

## Consequences

- **No number in this repository is a clinical result.** The AUC, the calibration, the fairness
  disparities and the cost avoided are properties of this generator and of the models trained on
  it, and the README, the model card and `docs/evaluation.md` say so. They demonstrate the
  lifecycle and the arguments, not the medicine.
- The disparities the fairness audit finds are the ones the generator induces through
  deprivation, language barrier and age; they are realistic in direction, invented in size.
- CTGAN's contribution is deliberately narrow — the joint distribution of age and deprivation
  under the documented categorical marginals — because that is the part of the problem it
  measurably does well here; the structure that gives the data its meaning is explicit code that
  a reviewer can read.
- Generation needs `torch`, kept in `requirements-synth.txt` so the runtime image, the components
  and CI never install it.
- A real deployment replaces the generator with an extract pipeline and keeps everything from
  `prep` onwards; the schema is the contract that makes that swap visible.

## Rejected

- **A public benchmark** (diabetes readmission, MIMIC-derived tables): none carries adherence and
  socioeconomic proxies, and the famous ones would make the repository look like a tutorial.
- **A purely parametric cohort without CTGAN**: simpler and fully explicit, but then the published
  rows would be the equations' own draws; the GAN stage is what separates them from the seed.
- **CTGAN over all 57 features, label redrawn**: the first implementation; measured above, it
  destroys the feature relationships that make the explanations and the fairness audit mean
  anything.
- **A label learned by the GAN**: it makes the signal strength a side effect of training epochs,
  which is the wrong thing to be uncertain about.
