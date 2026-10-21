"""Weekly batch scoring: the batch endpoint scores the cohort and the scores become the ranked call list.

The deliverable is not a probability but a list: who to call this week, in what order, and what
each call is expected to save. The batch endpoint runs the scoring module over the cohort data
asset; this script ranks the scores, drops contacts below break-even, keeps as many as the
programme can make, writes the list where the API serves it and reports the expected cost avoided.
"""

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd
import psycopg
from azure.ai.ml import Input, MLClient

from ops.data_asset import ASSET, workspace
from src import cohorts
from src.economics import Economics

COLUMNS = ["person_id", "score"]
INSERT = "INSERT INTO call_list (rank, person_id, score, expected_value_eur) VALUES (%s, %s, %s, %s)"


def score_cohort(client: MLClient, endpoint: str, data_asset: str, folder: Path) -> pd.DataFrame:
    """Invokes the batch endpoint on the data asset, waits, and reads the appended rows back."""
    cohort = Input(type="uri_file", path=f"azureml:{data_asset}")
    job = client.batch_endpoints.invoke(endpoint_name=endpoint, inputs={"cohort": cohort})
    client.jobs.stream(job.name)
    client.jobs.download(job.name, download_path=str(folder), output_name="score")
    return pd.read_csv(next(folder.rglob("predictions.csv")), header=None, names=COLUMNS, sep=None, engine="python")


def call_list(scored: pd.DataFrame, economics: Economics, capacity: int) -> pd.DataFrame:
    """Ranked by score, priced by the gate's economics, only contacts that pay, as many as the programme can make."""
    ranked = scored.assign(expected_value_eur=economics.expected_value(scored["score"].to_numpy())).sort_values(
        "score", ascending=False
    )
    ranked = ranked[ranked["score"] > economics.break_even].head(capacity).reset_index(drop=True)
    ranked.insert(0, "rank", ranked.index + 1)
    return ranked


def publish(conn: psycopg.Connection[Any], listed: pd.DataFrame) -> None:
    """Replaces this week's list; the table and its grants belong to `ops/pg_roles.py`."""
    conn.execute("DELETE FROM call_list")
    values = listed[["rank", "person_id", "score", "expected_value_eur"]].to_numpy().tolist()
    rows = [(int(rank), int(person), float(score), float(value)) for rank, person, score, value in values]
    with conn.cursor() as cursor:
        cursor.executemany(INSERT, rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-version", default="1")
    parser.add_argument("--capacity", type=int, default=int(os.environ.get("WEEKLY_CAPACITY", 200)))
    parser.add_argument("--out", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    scored = score_cohort(workspace(), os.environ["BATCH_ENDPOINT"], f"{ASSET}:{args.data_version}", args.out)
    listed = call_list(scored, Economics.from_env(), args.capacity)
    listed.to_csv(args.out / "call_list.csv", index=False)
    with cohorts.connect() as connection:
        publish(connection, listed)
    print(f"{len(listed)} contacts this week, expected cost avoided {listed['expected_value_eur'].sum():,.0f} €")
