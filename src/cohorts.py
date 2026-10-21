"""Cohort similarity in PostgreSQL with pgvector: the forty most similar patients and what worked for them.

A care manager trusts a precedent more than a probability. A patient's embedding is the SHAP
vector of their score, so "similar" means "at risk for the same reasons", searched by cosine
distance over HNSW (ADR-006); "what worked" is the neighbours' readmission rate with and without
care-manager contact. `ops/pg_roles.py` owns schema and grants; connections use Entra tokens.
"""

import argparse
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from azure.identity import DefaultAzureCredential
from pgvector.psycopg import register_vector

from src.economics import Array
from src.scoring.score import Scorer

SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
NEIGHBOURS = 40
FACTS = ("person_id", "readmission_30d", "care_manager_contacts_12m", "pdc_180d", "has_caregiver", "age")
UPSERT = "INSERT INTO patients VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (person_id) DO UPDATE SET"
UPSERT += " embedding = EXCLUDED.embedding, readmission_30d = EXCLUDED.readmission_30d"
NEAREST = f"SELECT {', '.join('p.' + f for f in FACTS)}, 1 - (p.embedding <=> q.embedding) FROM patients p, patients q"
NEAREST += " WHERE q.person_id = %s AND p.person_id <> %s ORDER BY p.embedding <=> q.embedding LIMIT %s"


def connect() -> psycopg.Connection[Any]:
    """Entra token as password; the user is whoever runs this (operator, pipeline identity or API identity)."""
    env, token = os.environ, DefaultAzureCredential().get_token(SCOPE).token
    conn = psycopg.connect(
        host=env["POSTGRES_HOST"], dbname=env["POSTGRES_DATABASE"], user=env["POSTGRES_USER"], password=token
    )
    conn.autocommit = True
    register_vector(conn)
    return conn


def load(conn: psycopg.Connection[Any], frame: pd.DataFrame, embeddings: Array) -> int:
    facts = frame[list(FACTS)].to_numpy().tolist()
    rows = [
        (int(p), e, bool(r), int(c), float(d), bool(g), float(a))
        for (p, r, c, d, g, a), e in zip(facts, embeddings, strict=True)
    ]
    with conn.cursor() as cursor:
        cursor.executemany(UPSERT, rows)
    return len(rows)


def rate(part: pd.DataFrame, column: str = "readmission_30d") -> float:
    return float(np.mean(part[column].to_numpy(dtype=float))) if len(part) else float("nan")


def what_worked(neighbours: pd.DataFrame) -> dict[str, float]:
    """The precedent in numbers a care manager can act on: readmission with and without care-manager contact."""
    contacted = neighbours["care_manager_contacts_12m"] > 0
    summary = {"neighbours": len(neighbours), "readmission_rate": rate(neighbours)}
    summary |= {"mean_pdc": rate(neighbours, "pdc_180d")}
    summary |= {"readmission_rate_with_care_manager": rate(neighbours[contacted])}
    summary |= {"readmission_rate_without_care_manager": rate(neighbours[~contacted])}
    return summary | {"share_with_caregiver": rate(neighbours, "has_caregiver")}


def similar(conn: psycopg.Connection[Any], person_id: int, k: int = NEIGHBOURS) -> dict[str, Any]:
    rows = conn.execute(NEAREST, (person_id, person_id, k)).fetchall()
    neighbours = pd.DataFrame(rows, columns=[*FACTS, "similarity"])
    found = {"neighbours": neighbours.to_dict(orient="records"), "what_worked": what_worked(neighbours)}
    return {"person_id": person_id} | found


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    cohort, scorer = pd.read_parquet(args.cohort), Scorer(args.model)
    vectors = scorer.contributions(cohort).to_numpy(dtype=np.float32)
    with connect() as connection:
        print(f"loaded {load(connection, cohort, vectors)} patients with {vectors.shape[1]}-dimensional embeddings")
