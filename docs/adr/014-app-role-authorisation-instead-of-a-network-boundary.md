# ADR-014 · App-role authorisation instead of a network boundary

**Status:** accepted · **Date:** 2026-10-21

## Context

The API returns a list of patients to call and, for any patient, the forty most similar ones. Even
on synthetic data, it should be built as if the records were real. The landing zone this workload
runs in has no virtual network, by decision: identity is the security boundary, every service
accepts Entra tokens only, and the landing zone's ADR-002 records what private networking would add
and why it is not deployed. This repository follows that posture rather than re-arguing it.

## Options

1. **A private network**: the API, the workspace and PostgreSQL behind private endpoints.
2. **Identity at every hop**, with an app role on the API.

## Decision

**Option 2.** Every hop authenticates with Entra ID and authorises with the narrowest role:

- **The API** requires a token at the Container Apps ingress, and the code checks the signature,
  the audience and the **`Care.Read` app role**. A token from the same tenant without the role gets
  403. Authentication at the ingress proves who is calling; the role in the code decides what they
  may see.
- **The endpoints** use `aad_token` authentication; there are no keys.
- **PostgreSQL** accepts Entra tokens only, with password authentication disabled. The API identity
  can only read, and the deployment identity can only write rows (`ops/pg_roles.py`).
- **Storage, registry and workspace** are reached by managed identities with data roles; shared
  keys are disabled on the storage account.

## Consequences

- No public surface answers without a token, and no secret exists to leak.
- The API and the database are reachable on the internet by anyone who has a valid token and the
  role, which is the same trust the landing zone places in every workload.
- Operators connect from their own address through a single firewall rule for PostgreSQL.

## Revisit when

The landing zone adopts private networking, or real patient data arrives, at which point a
private endpoint in front of PostgreSQL and the workspace becomes a requirement rather than an
option.

## Rejected

- **A private network for this workload alone.** It would contradict the estate's posture, add DNS
  and private endpoints to every dependency, and still need the same identity checks behind it.
