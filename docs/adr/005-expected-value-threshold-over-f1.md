# ADR-005 · An expected-value threshold under capacity, not an F1 optimum

**Status:** accepted · **Date:** 2026-10-20

## Context

A classifier needs an operating point, and the reflex is to pick the threshold that maximises
F1 on the validation split. F1 weighs precision and recall equally and ignores two things the
programme cannot ignore: a false negative and a false positive have wildly different costs, and
the number of patients the programme can contact in a week is fixed by its nursing capacity, not
by the model.

With the programme's parameters (`.env.example`: a contact costs 35 €, a readmission 4,800 €, a
contact prevents 25 % of the readmissions it reaches) the expected value of contacting a patient
with readmission probability *p* is *p* × 0.25 × 4,800 − 35, which is positive above
*p* ≈ 0.029. At a base rate near 19 %, almost every patient clears that bar, so the threshold
that matters is not a probability at all: it is the capacity.

## Decision

`src/economics.py` prices policies, and the policy the repository acts on is **capacity first,
expected value second**:

- `Economics.expected_value(scores)` is the net euros of each contact, and `break_even` the
  probability above which a contact pays for itself. Both are exposed so the weekly call list
  (phase 7) can show the expected value of every contact and never schedule one that loses money.
- `contacted(scores, share)` is the capacity policy: the highest-scored share of the population,
  with `contact_share` defaulting to 0.02 (four weeks of 200 contacts against a cohort of
  40,000). It is a ranking rule, so a model is judged by how well it orders the top of the list.
- `cost_avoided(outcomes, chosen, economics)` prices any set of contacts the same way, so the
  F1 policy, the break-even policy and the capacity policy are compared in euros in experiment
  002 rather than argued about.
- `evaluate` reports the capacity policy (`cost_avoided_per_thousand`, `precision_at_capacity`,
  `contacts`) and `register` gates on it (ADR-003); the sweep (phase 6) optimises the same name
  on the validation split.

Calibration still matters, and is reported (Brier score, expected calibration error and the
reliability table), because the expected value of a contact is only honest if the probability
is. The ranking decides who is called; the calibrated probability decides what to tell the
director it is worth.

## Consequences

- The headline number is in euros per thousand contacts, which a buyer can multiply by their
  own capacity. It is also a number that depends on the programme's parameters, so the model
  card states them and `evaluate` takes them as inputs rather than reading them from the model.
- A model that is better calibrated but ranks the top 2 % worse is a worse model here, and the
  gate will say so. That is the intended behaviour, not a limitation.
- `tests/test_evaluation.py` fixes the break-even arithmetic and shows, on a toy ranking, that
  the break-even policy alone contacts almost everybody while the capacity policy keeps the
  contacts that pay most.

## Rejected

- **F1-optimal threshold.** Optimises a trade-off nobody asked for, at an operating point the
  programme cannot staff; experiment 002 measures what it costs.
- **Youden's J or a fixed sensitivity.** Clinically familiar, but equally blind to costs and
  capacity.
- **Optimising expected value without the capacity constraint.** The break-even probability is
  so low that the policy contacts nearly the whole cohort; the constraint is what makes the
  ranking matter.
