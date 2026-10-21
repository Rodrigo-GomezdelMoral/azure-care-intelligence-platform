# Experiment 002 · F1-optimal threshold versus capacity-constrained expected value

**Date:** 2026-10-20 · **Data asset:** `patient-cohort:1` · **Model:** `readmission-risk` v1
(gradient boosting, champion) · **Programme parameters:** contact 35 €, readmission 4,800 €,
effectiveness 25 %, capacity 2 % of the cohort (ADR-005)

## Hypothesis

Choosing the operating point by maximising F1, the textbook default, produces a call list the
programme cannot staff and a worse return per contact than ranking patients by risk and calling
as many as the capacity allows. The difference is large enough to be the product argument.

## Variants

Three rules for whom to contact, applied to the same scores on the same test split (6,000
patients, 1,133 readmitted), all priced by `src/economics.py`:

| Policy | Rule |
|---|---|
| `capacity` | the 120 highest scores (2 % of the population), the policy the repository acts on |
| `break_even` | every patient whose expected value is positive, i.e. score above 35 / (0.25 × 4,800) = 0.029 |
| `f1_optimal` | every patient above the threshold that maximises F1 on this split (0.216) |

## Method

`evaluate` prices all three on every run and logs them as `policy_<name>_<metric>`; the table
below is the champion's test split (`evaluate` of run `sweet_whistle_z17tfhcdr9`, reproduced
locally with `src.economics.policies` on the same model and split). Net euros are hits ×
effectiveness × readmission cost minus contacts × contact cost; "per thousand" divides by the
number of contacts.

## Results

| Policy | Contacts | Precision | Cost avoided per thousand contacts | Net euros on the split |
|---|---|---|---|---|
| `capacity` (top 2 %) | 120 | 0.758 | **875,000 €** | 105,000 € |
| `f1_optimal` (score ≥ 0.216, F1 = 0.475) | 1,863 | 0.382 | 422,971 € | 787,995 € |
| `break_even` (score > 0.029) | 6,000 | 0.189 | 191,600 € | 1,149,600 € |

The logistic regression of experiment 001 gives the same picture (120 contacts at 865,000 €;
F1 threshold 0.270 with 1,383 contacts at 492,549 €; break-even contacting 5,912).

## Reading the table

- The F1 optimum asks for **1,863 calls on a 6,000-patient split**, fifteen times the capacity.
  A programme that could only make 120 of them and took them in arbitrary order would avoid
  about 423,000 € per thousand contacts, half of what the ranked list avoids. F1 is not wrong
  about the data; it is answering a question nobody asked.
- Contacting everyone with positive expected value avoids the most money in total, because at
  a 19 % base rate nearly every contact pays for itself in expectation. That is the honest
  argument for a bigger programme, and the model card says so. It is not an argument about the
  model: with unlimited capacity the ranking does not matter.
- Under the real constraint, the ranking is the whole product: the top 2 % by score has a
  precision of 0.76 against a base rate of 0.19, and every slot in the weekly list is worth
  about 875 € of avoided cost.

## Decision

The operating point is **capacity first, expected value second** (ADR-005), unchanged. The
business metric reported, gated on and swept is cost avoided per thousand contacts at the
capacity cut, and the weekly call list (phase 7) ranks by score, shows the expected value of each
contact and never schedules one below break-even. F1 is reported nowhere, because no decision
depends on it.
