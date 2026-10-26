# Architecture

## Lifecycle

```mermaid
flowchart LR
    GEN["src/data/synthesize.py<br/>synthetic cohort, fixed seed"] --> DA[("data asset<br/>patient-cohort:N")]
    DA --> PREP["prep<br/>schema contract, splits"]
    subgraph PIPE["training pipeline, serverless"]
        PREP --> TRAIN["train<br/>or Bayesian sweep on cpu-cluster"]
        TRAIN --> EVAL["evaluate<br/>AUC, calibration, subgroups, euros"]
        EVAL --> REG{"register<br/>beats the champion?"}
    end
    REG -- "yes" --> CH["challenger<br/>registry tag"]
    REG -- "no" --> NO["refused, logged"]
    CH --> APPROVE{{"deploy-prod.yml<br/>named reviewer"}}
    APPROVE --> ONLINE["online endpoint<br/>blue/green, SHAP + templates"]
    APPROVE --> BATCH["batch endpoint<br/>weekly scoring"]
    APPROVE --> PG[("PostgreSQL + pgvector<br/>embeddings")]
    BATCH --> LIST[("call list")]
    LIST --> API["care manager API<br/>Care.Read"]
    PG --> API
    DA --> DRIFT["drift-check.yml<br/>evidently"]
    DRIFT -- "drift" --> ISSUE["GitHub issue"]
    DRIFT -- "drift" --> PIPE
```

A model reaches care managers only through the gate and an approval. Drift starts the pipeline but
never passes the gate on its own (ADR-007), and the gate never promotes (ADR-003, ADR-004).

| Stage | Workflow | Trigger | Ends at |
|---|---|---|---|
| dev | `train-dev.yml` | pull request | a comment with the run, the metrics and the gate's decision |
| staging | `train-staging.yml` | merge to `main` | a challenger or a refusal, with the comparison on the run |
| production | `deploy-prod.yml` | dispatch, approved by a named reviewer | 10 % then 100 % of traffic, champion tag, batch and embeddings refreshed |
| operations | `batch-weekly.yml` | Mondays 06:00 UTC | this week's call list in PostgreSQL |
| monitoring | `drift-check.yml` | Mondays 05:00 UTC | an issue and a retraining run, or nothing |
| quality | `ci.yml` | pull request | lint, types, tests, budget, component schemas, Bicep, gitleaks |

## Network and identity

```mermaid
flowchart TB
    GH["GitHub Actions"] -- "OIDC: main, pull_request,<br/>environment:production" --> CICD(["id-carecicd"])
    CM["care manager"] -- "Entra token,<br/>Care.Read" --> ACA["Container Apps<br/>ca-careapi"]
    subgraph RG["rg-careintel-prod-swc, no virtual network"]
        ACA -- "id-careapi, SELECT" --> PSQL[("PostgreSQL Flexible<br/>Entra only")]
        CICD -- "jobs, endpoints, rows" --> MLW["Azure ML workspace<br/>mlw-careintel-prod-swc"]
        CICD -- "rows" --> PSQL
        MLW -- "id-careaml" --> ST[("Storage<br/>shared keys off")]
        MLW --> KV[("Key Vault<br/>mandatory dependency")]
        MLW --> EP["online endpoint, DS1_v2, blue/green<br/>batch endpoint, aad_token"]
        MLW --> CL["cpu-cluster<br/>0 to 3 nodes"]
    end
    subgraph SHARED["landing zone, shared"]
        ACR[("container registry<br/>admin user off")]
        LAW[("Log Analytics")]
    end
    EP -- "id-careaml, AcrPull" --> ACR
    CL -- "id-careaml, AcrPull" --> ACR
    MLW -- "diagnostics" --> LAW
    ACA -- "diagnostics" --> LAW
    ST -- "diagnostics (blob)" --> LAW
```

There is no private network, by the landing zone's decision; every arrow is an Entra-authenticated
call with the narrowest role (`docs/security.md`, ADR-014). Alerts go to the landing zone's action
group: a failed run in the workspace, and server errors from the API. Drift raises a GitHub issue,
because it is computed in a workflow (ADR-007).
