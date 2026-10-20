# ADR-006 · pgvector for cohort similarity

**Status:** accepted · **Date:** 2026-10-20

## Context

A care manager who is handed a probability asks the same question every time: *who else looked
like this, and what happened to them?* A precedent is actionable in a way a number is not. The
requirement is therefore "show me the forty patients most similar to this one and what worked
with them", answered in well under a second from a service the API can call with an identity
and no key.

## Decision

**Azure Database for PostgreSQL Flexible Server with the `pgvector` extension**, already part of
the infrastructure, holds one row per patient with an embedding, the handful of facts the
precedent needs (readmission, care-manager contacts, adherence, caregiver, age) and an HNSW
index with cosine distance; `src/cohorts.py` is the whole implementation.

Three choices inside that decision:

- **The embedding is the vector of SHAP contributions of the patient's own score**, not the raw
  features. Raw features would need scaling and would call two patients similar because they
  share an age and a postcode; contributions are already on one scale (log-odds) and make
  "similar" mean "at risk for the same reasons", which is what a precedent is for. The same
  `Scorer` that explains a score produces the embedding, so there is one definition of a
  patient's risk profile in the repository.
- **Cosine distance over HNSW** (`vector_cosine_ops`, `<=>`), because the direction of the
  contribution vector carries the profile and its length mostly carries the score, and because
  HNSW gives sub-millisecond neighbourhoods on a 40,000-row table without tuning.
- **"What worked" is computed, not stored**: the readmission rate among the neighbours with and
  without care-manager contact, their mean adherence and caregiver share. On synthetic data this
  is the generator's effect of contact on adherence showing through; on real data it is the
  closest thing to evidence a care manager gets at the point of a call.

Access follows the identity table: the pipeline identity loads (`python -m src.cohorts`), the API
identity has `SELECT` and nothing else, and both connect with an Entra token as the password.

## Consequences

- One more table in a database the repository already runs, no new service, no new secret.
- The embedding changes when the champion changes, so the table is reloaded after a promotion
  (the deployment workflow's last step). Similarity results are therefore tied to a model
  version, and the API answers from the version currently loaded.
- Forty neighbours of 40,000 is a small neighbourhood; the HNSW parameters are PostgreSQL's
  defaults and were not tuned, because the recall at this size is not the problem.
- On synthetic data the precedent is only as real as the generator; the model card says so.

## Rejected

- **Azure AI Search vector index.** It exists in the landing zone, but it would add a second
  data store with its own identity and a copy of patient facts for a query PostgreSQL answers
  natively.
- **Nearest neighbours in the API process** (scikit-learn, FAISS): fast enough at this size,
  but the cohort would have to be loaded into every replica, and the precedent facts would live
  in memory instead of in the database the rest of the system reads.
- **Raw-feature embeddings with a fitted scaler**: another artefact to version and ship, and a
  weaker notion of similarity for the purpose.
