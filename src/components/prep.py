"""Validates a cohort extract against the schema, encodes it and splits it; fails loudly on drift.

`data/schema.json` is the contract with the data producer: a column that disappears, changes type
or arrives mostly empty stops the pipeline here, before anything is trained on it. Imputation and
encoding are fitted on the training split, so they live inside the model (`train`); this component
guarantees their contract and writes the stratified train, validation and test splits.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from sklearn.model_selection import train_test_split

SCHEMA = Path(__file__).resolve().parents[2] / "data" / "schema.json"
NOMINAL = ("gender_concept_id", "urbanicity", "employment_status", "insurance_type")
IDENTIFIER = "person_id"
MAX_MISSING = 0.05
SPLITS = {"train": 0.70, "validation": 0.15, "test": 0.15}


class SchemaDriftError(ValueError):
    """The extract does not match the schema the model was built for."""


def contract() -> dict[str, Any]:
    schema: dict[str, Any] = json.loads(SCHEMA.read_text(encoding="utf-8"))
    return schema


def compatible(actual: str, expected: str) -> bool:
    kinds = pd.api.types.pandas_dtype(actual).kind, pd.api.types.pandas_dtype(expected).kind
    return kinds[0] == kinds[1] or all(kind in "iuf" for kind in kinds)


def validate(frame: pd.DataFrame, schema: dict[str, Any]) -> pd.DataFrame:
    """Returns the columns in schema order, or raises `SchemaDriftError` naming every deviation."""
    columns: dict[str, dict[str, str]] = schema["columns"]
    present = [name for name in columns if name in frame.columns]
    problems = {
        "missing": sorted(set(columns) - set(frame.columns)),
        "unexpected": sorted(set(frame.columns) - set(columns)),
        "wrong_type": [n for n in present if not compatible(str(frame[n].dtype), columns[n]["dtype"])],
        "mostly_empty": [n for n in present if frame[n].isna().mean() > MAX_MISSING],
    }
    if any(problems.values()):
        raise SchemaDriftError(json.dumps({kind: names for kind, names in problems.items() if names}))
    return frame[list(columns)]


def encode(frame: pd.DataFrame) -> pd.DataFrame:
    """Booleans become 0/1 integers so every feature is numeric for the model, the explainer and the embedding."""
    flags = [name for name, dtype in frame.dtypes.items() if dtype.kind == "b"]
    return frame.astype(dict.fromkeys(flags, "int8"))


def split(frame: pd.DataFrame, label: str, seed: int) -> dict[str, pd.DataFrame]:
    """Stratified 70/15/15 split on the label, so the three readmission rates match."""
    held = SPLITS["validation"] + SPLITS["test"]
    train, rest = train_test_split(frame, test_size=held, stratify=frame[label], random_state=seed)
    validation, test = train_test_split(rest, test_size=SPLITS["test"] / held, stratify=rest[label], random_state=seed)
    return {"train": train, "validation": validation, "test": test}


def main(cohort: Path, outputs: dict[str, Path], seed: int) -> dict[str, int]:
    schema = contract()
    parts = split(encode(validate(pd.read_parquet(cohort), schema)), schema["label"], seed)
    for name, part in parts.items():
        outputs[name].parent.mkdir(parents=True, exist_ok=True)
        part.to_parquet(outputs[name], index=False)
        mlflow.log_metrics({f"{name}_rows": len(part), f"{name}_readmission_rate": float(part[schema["label"]].mean())})
    mlflow.log_params({"features": schema["features"], "seed": seed})
    return {name: len(part) for name, part in parts.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=7)
    for name in SPLITS:
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(main(args.cohort, {name: getattr(args, name) for name in SPLITS}, args.seed))
