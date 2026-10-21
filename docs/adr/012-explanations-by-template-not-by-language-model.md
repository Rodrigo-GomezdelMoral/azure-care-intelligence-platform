# ADR-012 · Explanations by deterministic template, not by language model

**Status:** accepted · **Date:** 2026-10-20

## Context

The online endpoint returns, with every score, the features that moved it most, translated
into language a care manager can use on the phone. The obvious modern way to produce that text
is to hand the SHAP values to a language model and ask for a sentence. In a clinical context
that is a defect, not a feature: the same patient would get different wording between two
calls, the text could not be audited line by line, and a model that writes freely about a
patient's risk is a model that can, one day, write something untrue.

## Decision

`src/scoring/score.py` translates contributions with **fixed templates keyed by feature**. A
template is a sentence fragment with the feature's value formatted into it ("took their
medication on 52 % of days over the last six months"); flags have two fixed fragments ("has a
caregiver" / "has no caregiver"); conditions and drugs use one generic pattern ("has heart
failure" / "does not have heart failure"); anything else falls back to the feature name and
its value. The direction comes from the sign of the SHAP value ("which raises the risk" /
"which lowers the risk"), and the three largest absolute contributions are reported, summed
back to the raw columns so a one-hot level never appears as a driver on its own. The templates
are a table in the module; adding a feature means adding a row, and the test suite pins the
exact text of several of them.

There is no agent anywhere in this repository (ADR-013), and this is the place where the
temptation was greatest.

## Consequences

- Two calls for the same patient and model produce the same words; a reviewer can read every
  sentence the system is able to say by reading one table.
- The language is plain but not fluent, and it does not combine drivers into a narrative. That
  is accepted: the sentence is a reason for a nurse to call, not a clinical note.
- Templates are in English only; localisation is a table per language, not a model.
- Contributions are in log-odds units and are shown as numbers next to the text, so a user who
  wants the magnitude has it without the text pretending to a precision it does not have.

## Revisit when

Users need another language, which is one more template table, or explanations that combine drivers into a sentence, which must stay deterministic and auditable.

## Rejected

- **A language model over the SHAP values.** Non-deterministic, unauditable, and able to
  produce text about a patient that the data does not support.
- **No text at all, only feature names and values.** Auditable but not usable on the phone; the
  translation is the product's half of the explanation.
