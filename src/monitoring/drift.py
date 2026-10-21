"""Detects drift between the cohort the champion was trained on and the current one, and retrains.

evidently tests every feature with its default for the column type and sample size (Wasserstein or
Jensen-Shannon distance at this cohort's size, p-values below a thousand rows), and the cohort has
drifted when the share of drifted features reaches the threshold. Drift submits the training
pipeline on the current data asset version, which ends at the registration gate: a better model
becomes a challenger, never the champion, and nothing here touches registry or traffic (ADR-007).
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from azure.ai.ml import Input, MLClient
from evidently import Report
from evidently.presets import DataDriftPreset

from ops.data_asset import ASSET, workspace
from pipelines.training import submit, training
from src.components.prep import IDENTIFIER, contract

THRESHOLD = 0.3


def drift(reference: pd.DataFrame, current: pd.DataFrame, threshold: float = THRESHOLD) -> dict[str, Any]:
    """evidently's verdict at this share of drifted features, and which features drifted."""
    features = [name for name in reference.columns if name not in (contract()["label"], IDENTIFIER)]
    report = Report([DataDriftPreset(drift_share=threshold)])
    metrics = report.run(current_data=current[features], reference_data=reference[features]).dict()["metrics"]
    tests = [(m["config"], float(m["value"])) for m in metrics if m["config"]["type"].endswith("ValueDrift")]
    moved = [(v < c["threshold"]) if "p_value" in c["method"] else (v > c["threshold"]) for c, v in tests]
    drifted = [config["column"] for (config, _), flag in zip(tests, moved, strict=True) if flag]
    share = next(float(m["value"]["share"]) for m in metrics if m["config"]["type"].endswith("DriftedColumnsCount"))
    return {"drift": share >= threshold, "share": round(share, 4), "threshold": threshold, "drifted": drifted}


def retrain(client: MLClient, version: str, identity: str) -> str:
    """The training pipeline on the current cohort; it stops at the registration gate and never promotes."""
    asset = f"{ASSET}:{version}"
    job = training(cohort=Input(type="uri_file", path=f"azureml:{asset}"), data_asset=asset)
    return str(submit(client, job, identity, {"data_asset": asset, "trigger": "drift"}, wait=False).name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--current-version", required=True)
    parser.add_argument("--retrain", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = drift(pd.read_parquet(args.reference), pd.read_parquet(args.current)) | {"current": args.current_version}
    if result["drift"] and args.retrain:
        result["retraining_run"] = retrain(workspace(), args.current_version, os.environ["AML_IDENTITY_CLIENT_ID"])
    if args.report:
        args.report.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result))
