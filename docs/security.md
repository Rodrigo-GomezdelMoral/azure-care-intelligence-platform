# Security

**Identity is the security boundary.** This workload follows the landing zone's posture, recorded in
its ADR-002: no virtual network, every service accepts Entra tokens only (ADR-014 here).

## Identities and roles

| Identity | Used by | Role | Scope |
|---|---|---|---|
| `id-careaml` | pipeline steps, sweep trials, `cpu-cluster`, online and batch deployments | AzureML Data Scientist | workspace |
| | | Storage Blob, Table and Queue Data Contributor | workspace storage account |
| | | AcrPull | shared container registry |
| `id-careapi` | the API container app | AcrPull | shared container registry |
| | | `SELECT` on `patients` and `call_list` | PostgreSQL `care` |
| `id-carecicd` | the GitHub workflows, by OIDC federation | AzureML Data Scientist | workspace |
| | | Storage Blob Data Contributor | workspace storage account |
| | | Managed Identity Operator, to attach `id-careaml` to an endpoint | `id-careaml` |
| | | `SELECT, INSERT, UPDATE, DELETE` on `patients` and `call_list` | PostgreSQL `care` |
| workspace system identity | image builds | Storage Blob Data Contributor, File Data Privileged Contributor, Key Vault Administrator, Azure AI Administrator, granted by Azure Machine Learning itself | workspace resources |
| | | AcrPull | shared container registry |
| operator | `make` targets from a workstation | Storage Blob Data Contributor; PostgreSQL Entra administrator | storage account, server |

`id-carecicd` trusts exactly three GitHub subjects, each under the repository's immutable subject
prefix with its owner and repository ids: `ref:refs/heads/main` for the merge, schedule
and dispatch workflows, `pull_request` for `train-dev.yml`, and `environment:production` for
`deploy-prod.yml`. No workflow holds a secret beyond those identifiers.

## Data stores

- **Storage** has shared keys disabled; the workspace datastores use identity-based access.
- **Key Vault** exists only because Azure Machine Learning requires one; this repository writes
  nothing to it.
- **PostgreSQL** accepts Entra tokens only, with password authentication disabled, behind a
  firewall that admits Azure services and the operator's address. Bicep cannot create database
  roles or tables, which are data-plane objects, so `ops/pg_roles.py` creates them, run once by the
  server's Entra administrator; the deployment identity writes rows and never owns the schema.

## Endpoints and API

- The online and batch endpoints use `aad_token` authentication; there are no keys.
- The API requires an Entra token at the Container Apps ingress, and its code checks the
  signature, the audience, the tenant's issuer and the `Care.Read` app role: a token without the
  role gets 403. The check is on by default and fails closed; local runs set `REQUIRE_AUTH=false`.

## Synthetic data and privacy by design

No real patient data exists anywhere in this repository or its workspace. Every record comes from
`src/data/synthesize.py`, the schema is a contract rather than an extract, and no tabular file has
ever been committed. The data asset carries the SHA-256 of the file it registered, so any record a
run used can be traced to the generator. A real deployment would replace the generator with an
extract pipeline under a data processing agreement and add a private network (ADR-014).
