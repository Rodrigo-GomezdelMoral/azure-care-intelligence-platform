# Cost

List prices for Sweden Central in euros, read from the Azure retail prices API on 2026-10-21. They
exclude discounts, taxes and the landing zone's shared services, which this workload only consumes.

## Per run

| Activity | Compute | Measured | Approximate cost |
|---|---|---|---|
| Training pipeline, four steps | serverless `Standard_DS3_v2`, 0.2394 €/h | 1.5 to 3 minutes of step time, 3 to 6 minutes of wall time, plus about a minute of provisioning per step | about 0.05 € |
| Pipeline with the sweep, twelve trials | trials on `cpu-cluster`, `Standard_DS2_v2`, 0.1197 €/h, three at a time | measured by `train-staging.yml` on each run | under 0.50 € |
| Weekly batch scoring of 40,000 patients | `cpu-cluster`, one node | 6 minutes including scale-up | about 0.01 € |
| First run after an environment change | image build | about 4 minutes | negligible |

## Per month, always on

| Resource | Size | €/hour | €/month |
|---|---|---|---|
| **Online endpoint**, one instance | `Standard_DS1_v2` | 0.0598 | **44** |
| PostgreSQL Flexible Server | Burstable B2s | 0.0350 | 26 |
| PostgreSQL, the size the specification asked for | Burstable B1ms | 0.0175 | 13 |
| Container Apps API | consumption, scales to zero | | under 1 at demo traffic |
| Compute cluster `cpu-cluster` | 0 nodes when idle | | 0 |

PostgreSQL runs B2s because Sweden Central had no B1ms capacity when the infrastructure was
deployed (`POSTGRES_SKU`); that costs about 13 € a month more. Storage, Key Vault and Application
Insights add cents at this volume.

The online endpoint is the largest line, and it serves a care manager's occasional question. It
runs on `Standard_DS1_v2` because every deployment reserves a second instance's worth of quota for
upgrades: one `Standard_DS2_v2` deployment held 4 of the subscription's 6 DSv2 vCPUs, so blue and
green could not coexist, while two DS1_v2 deployments need 4. It is deleted between
demonstrations, `deploy-prod.yml` recreates it in about ten minutes, and the runbook has the
command. Training steps, sweep trials and deployments draw on the same family quota, so a quota
of 6 vCPUs serialises them; a higher quota only makes them faster.

## What a persistent cluster would cost

| Alternative | €/month |
|---|---|
| One `Standard_DS3_v2` node kept warm for training | 175 |
| The same for the sweep, three `Standard_DS2_v2` nodes | 262 |

Against a few euros a month of actual training, ADR-002 keeps training on serverless compute and
the one cluster at zero nodes.
