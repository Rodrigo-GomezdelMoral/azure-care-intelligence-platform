"""Registers the evaluated model only if it beats the champion on the business metric (ADR-003).

A version carries its test metrics and data asset as tags. The first becomes the champion; a later
one becomes a challenger only if its cost avoided per thousand contacts beats the champion's by the
margin, and ties lose. A refusal is logged and written for the workflow to publish. Promotion stays
a human decision in the deployment workflow, recorded in the version tag `stage`, because the
workspace registry accepts neither MLflow aliases nor the deprecated stages API.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any

import mlflow
from mlflow import MlflowClient
from mlflow.entities.model_registry import ModelVersion
from mlflow.models import Model

from src.economics import METRIC

STAGE, CHAMPION, CHALLENGER, REJECTED = "stage", "champion", "challenger", "rejected"


def champion(client: MlflowClient, name: str) -> ModelVersion | None:
    versions = client.search_model_versions(f"name='{name}'")
    return next((version for version in versions if version.tags.get(STAGE) == CHAMPION), None)


def decide(incumbent: float | None, challenger: float, min_improvement: float = 0.0) -> str:
    """Champion when there is nothing to beat; challenger when it beats the champion by the margin; else rejected."""
    if incumbent is None:
        return CHAMPION
    return CHALLENGER if challenger > incumbent + min_improvement else REJECTED


def register(path: Path, name: str, tags: dict[str, str]) -> ModelVersion:
    """Logs the model under this run, so the registry links the version to the pipeline that produced it."""
    saved = Model.load(path)
    model = mlflow.sklearn.load_model(str(path))
    example = saved.load_input_example(str(path))
    info = mlflow.sklearn.log_model(model, artifact_path="model", signature=saved.signature, input_example=example)
    version: ModelVersion = mlflow.register_model(info.model_uri, name, tags=tags)
    return version


def compare(report: dict[str, Any], incumbent: ModelVersion | None, min_improvement: float) -> dict[str, Any]:
    decision: dict[str, Any] = {"challenger": report["metrics"][METRIC], "min_improvement": min_improvement}
    decision |= {"champion": float(incumbent.tags[METRIC]) if incumbent else None}
    decision |= {"champion_version": str(incumbent.version) if incumbent else None}
    decision["decision"] = decide(decision["champion"], decision["challenger"], min_improvement)
    return decision


def main(args: argparse.Namespace) -> dict[str, Any]:
    """One run per registration attempt; the comparison is logged whether or not a version is created."""
    report = json.loads(args.metrics.read_text(encoding="utf-8"))
    with mlflow.start_run():
        decision = compare(report, champion(MlflowClient(), args.model_name), args.min_improvement)
        if decision["decision"] != REJECTED:
            tags = {name: f"{value:.4f}" for name, value in report["metrics"].items()}
            tags |= {STAGE: decision["decision"], "data_asset": args.data_asset}
            tags |= {"pipeline_run": os.environ.get("AZUREML_ROOT_RUN_ID", "local")}
            decision["registered_version"] = register(args.model, args.model_name, tags).version
        mlflow.log_params({name: str(value) for name, value in decision.items()})
    args.decision.parent.mkdir(parents=True, exist_ok=True)
    args.decision.write_text(json.dumps(decision, indent=1), encoding="utf-8")
    return decision


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--model-name", default="readmission-risk")
    parser.add_argument("--data-asset", required=True)
    parser.add_argument("--min-improvement", type=float, default=0.0)
    print(main(parser.parse_args()))
