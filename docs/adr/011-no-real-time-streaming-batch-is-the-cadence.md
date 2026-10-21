# ADR-011 · Rejected: real-time streaming; batch is the cadence of a weekly call list

**Status:** accepted · **Date:** 2026-10-21

## Context

The deliverable is a list a care team works through during the week: who to call, in what order,
and what each call is expected to save. Streaming architectures, event hubs feeding an online model
on every prescription refill, promise fresher scores.

## Options

1. **Event streaming** with scoring on every new event.
2. **A weekly batch** over the latest cohort, plus an online endpoint for the occasional single
   patient a care manager wants explained.

## Decision

**Option 2.** `batch-weekly.yml` invokes the batch endpoint every Monday and replaces the call list
in PostgreSQL; the online endpoint answers one patient at a time when someone asks why. The
binding constraint is the team's weekly capacity, not the freshness of the score: a probability
updated on Tuesday afternoon does not change a list the team planned on Monday morning.

## Consequences

- One batch job a week, a few minutes of a cluster that otherwise sits at zero nodes.
- Adherence signals that change mid-week, a missed refill, wait for the next run. For a 30-day
  readmission horizon and a weekly plan, that delay does not change who is called.

## Revisit when

The programme moves to same-day interventions, such as a call within hours of a discharge, where
the event itself is the trigger and the score has to follow it.

## Rejected

- **Event streaming.** It buys freshness the workflow cannot use, at the cost of an always-on
  ingestion path and online features.
