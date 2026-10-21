# ADR-004 · Champion and challenger through GitHub Environments

**Status:** accepted · **Date:** 2026-10-21

## Context

The registration gate (ADR-003) decides whether a new model is worth registering. Whether it
should replace the model a care team is acting on is a different decision, with a different owner:
someone who reads the comparison, the subgroup audit and the change in who would be called, and
who answers for the switch. That decision needs a named person, an audit trail and a way back.

## Options

1. **Promotion inside the training pipeline** when the gate passes.
2. **Promotion by hand** in the studio or the CLI.
3. **A deployment workflow behind a GitHub Environment with a required reviewer.**

## Decision

**Option 3.** The flow mirrors the official MLOps pattern in three stages:

| Stage | Trigger | What happens | Who decides |
|---|---|---|---|
| dev | pull request | `train-dev.yml` trains and comments the run, its test metrics and the gate's decision on the pull request | the reviewer of the pull request |
| staging | merge to `main` | `train-staging.yml` runs the pipeline with the sweep; the gate registers a challenger or refuses it, and the comparison is published on the run | the gate |
| production | `workflow_dispatch` | `deploy-prod.yml` deploys the chosen version to the idle colour at 10 % of traffic, smoke-checks it, shifts 100 %, retags it `champion` and retires the previous one | the named reviewer of the `production` environment |

Nothing in `deploy-prod.yml` runs before the reviewer approves. A failure before the registry
retag returns traffic to the colour that was serving, and the runbook covers a manual rollback
after it. The workflow's OIDC subject is `environment:production`, one of the three federated
credentials of `id-carecicd`.

## Consequences

- Every production change has a person, a time and a version attached, in the environment's
  deployment history.
- Production lags staging until someone approves, which is the point.
- The protection rule lives in the repository settings, not in a file: the README lists it as part
  of the bootstrap, and a workflow without it would deploy on dispatch.

## Revisit when

The organisation adopts an approval system outside GitHub, such as a change board with its own
records, or the model is promoted often enough that an automated canary analysis would carry more
evidence than a reviewer.

## Rejected

- **Promotion inside the pipeline.** It is the self-promotion ADR-007 rejects for drift, with the
  same failure mode.
- **Promotion by hand.** No approval record, no smoke check, no automatic rollback.
