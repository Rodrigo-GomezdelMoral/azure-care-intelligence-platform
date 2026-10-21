# ADR-002 · Serverless compute over a persistent cluster

**Status:** accepted · **Date:** 2026-10-21

## Context

This model trains a few times a month: on a pull request, on a merge, when drift is detected. A
compute cluster sized for training and kept warm bills every hour of the month for minutes of
work. The specification asks for nothing to run when nothing is training, and for the cost of the
alternative to be stated.

## Options

1. **Serverless compute** for every training step: Azure Machine Learning provisions a node per
   step and releases it.
2. **A persistent `AmlCompute` cluster** with at least one node, ready for every job.
3. **A cluster that scales to zero** for everything.

## Decision

**Option 1 for training, with one documented exception.** The four pipeline steps run on
serverless compute, `Standard_DS3_v2`, one node each, as the pipeline identity `id-careaml`.
Nothing is provisioned between runs.

The exception is `cpu-cluster`: `Standard_DS2_v2`, **zero** to three nodes, five minutes of idle
before scaling down, carrying `id-careaml` as its identity. It exists for two measured reasons:

- **Batch deployments run only on compute clusters**, AmlCompute or Kubernetes, never on
  serverless compute (documented by Azure Machine Learning).
- **The sweep's trials cannot run on serverless compute here.** A sweep node inside a pipeline
  loses its identity in both the SDK and the service, so its trials ran without `id-careaml` and
  could not pull their image from the shared registry, whose admin user is disabled (three runs on
  2026-10-20). On the cluster, the trials pull with the cluster's own identity.

At zero nodes the cluster costs nothing, so the principle holds: nothing runs when nothing is
working.

## Consequences

- A training run costs a few node-minutes, and every step pays a provisioning delay of one to two
  minutes. `docs/cost.md` prices a run and the persistent alternative: one `Standard_DS3_v2` node
  kept warm is about 175 € a month at list price.
- The first run after an environment change builds an image, about four minutes; later runs reuse
  it.
- Serverless quota is per VM family, and a busy subscription can queue a step; the runbook covers
  it.

## Revisit when

Training becomes frequent enough that provisioning delay dominates, more than a few runs a day, or
the service starts honouring a sweep node's identity, which would let the trials return to
serverless compute.

## Rejected

- **A persistent cluster for everything.** It bills for idle time to save minutes the process does
  not need.
- **The cluster for training too.** It would work, but it gives up per-step sizing and makes every
  pipeline wait for a shared scale-up.
