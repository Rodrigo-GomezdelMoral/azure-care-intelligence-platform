# Experiment 003 · What closing a subgroup gap costs

**Date:** 2026-10-21 · **Data asset:** `patient-cohort:1` · **Model:** `readmission-risk` v1, the
champion · **Split:** the `prep` test split, seed 7, 6,000 patients · **Script:**
`examples/fairness_mitigation.py`, which reads the same modules the pipeline runs

## Hypothesis

The audit of the champion (`docs/evaluation.md`) shows two gaps at the operating point. Patients
without insurance are reached less often than their readmissions warrant: recall 0.038 against
0.086 for public insurance, a parity ratio of 0.44. And patients under 65 are almost never
contacted: selection-rate parity 0.014 across age bands. The hypothesis is that each gap can be
closed by a contact policy rather than by retraining, and that closing it costs little in cost
avoided.

## Variants

| Variant | Rule |
|---|---|
| Baseline | the 120 highest scores, the capacity policy of ADR-005 |
| Quota by insurance | the 120 contacts allocated across insurance groups in proportion to each group's expected readmissions, the sum of its scores, then the highest scores within each group |
| Unaware | a model retrained without `insurance_type`, same parameters, top 120 |
| Quota by age band | the same need-proportional allocation across age bands |

## Method

`python examples/fairness_mitigation.py --train train.parquet --test test.parquet --model model/`
on the splits `prep` writes for `patient-cohort:1` with seed 7 and the champion downloaded from the
registry. Every variant is priced by `src/economics.py` and audited by `src/fairness.py`, the code
the pipeline runs.

## Results

| Variant | Contacts | Precision | Cost avoided per thousand | Recall parity, insurance | Recall none / private / public | Selection parity, age |
|---|---|---|---|---|---|---|
| Baseline | 120 | 0.758 | 875,000 € | 0.437 | 0.038 / 0.082 / 0.086 | 0.014 |
| Quota by insurance | 120 | 0.767 | 885,000 € | 0.792 | 0.066 / 0.082 / 0.083 | 0.014 |
| Unaware | 120 | 0.758 | 875,000 € | 0.437 | 0.038 / 0.082 / 0.086 | 0.014 |
| Quota by age band | 120 | 0.642 | 735,000 € | 0.620 | 0.047 / 0.076 / 0.067 | 0.405 |

## Reading the table

- **The insurance gap is noise, not bias.** The generator gives insurance no causal role (ADR-008),
  and the three insurance groups have the same mean age, deprivation and adherence. The model does
  not use the feature: retrained without it, it is the same model, to the patient. The gap is a
  small-group effect, 592 uninsured patients in the split and seven of them contacted. The
  need-proportional quota still closes most of it at no cost: one more readmitted patient found,
  inside the sampling noise of 10,000 € per patient.
- **The age gap is real risk, and closing it is expensive.** Patients aged 75 and over are
  readmitted at 0.33, those under 65 at 0.12. Allocating contacts by age band in proportion to
  expected readmissions raises the selection parity from 0.014 to 0.405 and costs 140,000 € per
  thousand contacts, 16 % of the value, because it calls patients the model correctly ranks as
  lower risk.
- **Removing a sensitive feature is not a mitigation here.** Fairness through unawareness changes
  nothing when the feature carries no signal, and when it does, its proxies carry it anyway.

## Decision

- **Keep the capacity policy as the default**, and keep the subgroup audit on every evaluation so
  that a gap is a known fact before a model is promoted.
- **Offer the need-proportional quota as a programme policy** for attributes where equal
  opportunity is the goal and risk is comparable across groups, such as insurance: it costs
  nothing measurable here, and on real data, where such a gap could reflect access barriers, it is
  the cheapest fix.
- **Do not equalise selection rates across groups whose risk genuinely differs**, such as age: the
  target there is equal opportunity among patients of comparable risk, and a 16 % loss of value is
  paid by the patients the programme would have reached.

The choice of a quota is the programme owner's, not the model's; the model card records the
audit and these numbers.
