"""Reports what the model is worth on the held-out test split: discrimination, calibration, euros.

Discrimination (AUC, average precision) says whether the ranking is right. Calibration (Brier
score, expected calibration error and the reliability table behind it) says whether the
probabilities can be trusted when the expected value of a contact is computed from them. The
business metric says what the ranking is worth under the programme's capacity, and is the number
the registration gate compares. Everything is logged to MLflow and written to `metrics.json`;
phase 5 adds the subgroup audit to the same report.
"""

import argparse
import json
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score

from src.components.prep import IDENTIFIER, contract
from src.economics import Array, Economics, arguments, summary

BINS = 10


def calibration(outcomes: Array, scores: Array) -> tuple[float, list[dict[str, float]]]:
    """Expected calibration error over ten equal-count bins, and the reliability table behind it."""
    frame = pd.DataFrame({"outcome": outcomes.astype(float), "score": scores})
    frame["bin"] = pd.qcut(frame["score"].rank(method="first"), BINS, labels=False)
    table = frame.groupby("bin").agg(
        predicted=("score", "mean"), observed=("outcome", "mean"), patients=("score", "size")
    )
    error = float((table["patients"] / len(frame) * (table["predicted"] - table["observed"]).abs()).sum())
    rows = [{str(k): float(v) for k, v in row.items()} for row in table.reset_index().to_dict(orient="records")]
    return error, rows


def evaluate(model: Any, test: pd.DataFrame, economics: Economics) -> dict[str, Any]:
    label = contract()["label"]
    features = [name for name in test.columns if name not in (label, IDENTIFIER)]
    scores = np.asarray(model.predict_proba(test[features])[:, 1], dtype=float)
    outcomes = test[label].to_numpy()
    error, table = calibration(outcomes, scores)
    metrics = {"auc": roc_auc_score(outcomes, scores), "average_precision": average_precision_score(outcomes, scores)}
    metrics |= {"brier": brier_score_loss(outcomes, scores), "calibration_error": error, "patients": len(test)}
    metrics |= summary(outcomes, scores, economics)
    return {"metrics": {name: float(value) for name, value in metrics.items()}, "calibration": table}


def main(args: argparse.Namespace) -> dict[str, float]:
    model = mlflow.sklearn.load_model(str(args.model))
    report = evaluate(model, pd.read_parquet(args.test), Economics.from_args(args))
    mlflow.log_metrics(report["metrics"])
    mlflow.log_dict(report, "evaluation.json")
    args.metrics.parent.mkdir(parents=True, exist_ok=True)
    args.metrics.write_text(json.dumps(report, indent=1), encoding="utf-8")
    metrics: dict[str, float] = report["metrics"]
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    arguments(parser)
    print(main(parser.parse_args()))
