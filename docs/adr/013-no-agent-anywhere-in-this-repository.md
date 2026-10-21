# ADR-013 · Rejected: an agent anywhere in this repository

**Status:** accepted · **Date:** 2026-10-21

## Context

The rest of this portfolio is built on Microsoft Agent Framework: a retrieval platform and a
field-operations copilot where language models plan, call tools and hand work to each other. A
reader moving from those repositories to this one will notice that nothing here is an agent, and
should find out why in one place.

The rule the portfolio follows is that if a task can be written as a function, it should be a
function. An agent earns its place when the task is open-ended: the inputs vary in shape, the
steps are not known in advance, and judgement over tools is the work.

## Options

1. **An agent somewhere in the loop**: a model that explains scores in prose, triages drift, or
   drafts the call list.
2. **No agent**: supervised learning on tabular data, deterministic serving, people at the
   decisions that need judgement.

## Decision

**Option 2.** Every task in this system has a known shape. Ranking patients is a supervised model
with a business metric (ADR-005); explaining a score is a fixed template over SHAP values
(ADR-012); detecting drift is a statistical test with a threshold (ADR-007); promoting a model is a
human approval (ADR-004). `agent_framework` appears in no requirement and no import.

The places where an agent was tempting are exactly the places where determinism matters most. An
explanation that changes wording between two calls for the same patient is a defect in a clinical
setting; a drift triage that improvises is an unaudited decision about which model treats whom.

## Consequences

- The system is reproducible end to end: the same data asset, component versions and parameters
  give the same scores, explanations and decisions.
- There is no conversational surface. A care manager asks two questions, the list and the
  precedent, and gets structured answers.

## Revisit when

The task stops having a known shape: for example, if care managers need to ask open questions over
clinical notes, where retrieval and reasoning are the work. That would be a separate service with
its own evaluation, as the copilot in this portfolio is, not a change to this one.

## Rejected

- **A language model writing explanations.** Non-deterministic, unauditable, able to state what the
  data does not support.
- **An agent triaging drift.** The decision is a threshold and a human review, and both are
  cheaper and more defensible.
