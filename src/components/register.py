"""Registers the evaluated model in the workspace registry and marks the champion with a tag.

A registered version carries the metrics it earned on the test split and the data asset it was
trained on as tags, so a reviewer reads the comparison without opening a run. The first version
becomes the champion; every later one is registered as a challenger. Phase 5 turns this into the
gate that refuses a challenger that does not beat the champion on the business metric, and
promoting a challenger to champion stays a human decision taken in the deployment workflow. The
role is the version tag `stage`, because the workspace registry accepts neither MLflow aliases
nor the deprecated stages API.
"""

import argparse
import json
import os
from pathlib import Path

import mlflow
from mlflow import MlflowClient
from mlflow.entities.model_registry import ModelVersion
from mlflow.models import Model

STAGE, CHAMPION, CHALLENGER = "stage", "champion", "challenger"


def champion(client: MlflowClient, name: str) -> ModelVersion | None:
    versions = client.search_model_versions(f"name='{name}'")
    return next((version for version in versions if version.tags.get(STAGE) == CHAMPION), None)


def register(path: Path, name: str, tags: dict[str, str]) -> ModelVersion:
    """Logs the model under this run, so the registry links the version to the pipeline that produced it."""
    saved = Model.load(path)
    model = mlflow.sklearn.load_model(str(path))
    example = saved.load_input_example(str(path))
    info = mlflow.sklearn.log_model(model, artifact_path="model", signature=saved.signature, input_example=example)
    version: ModelVersion = mlflow.register_model(info.model_uri, name, tags=tags)
    return version


def main(args: argparse.Namespace) -> str:
    report = json.loads(args.metrics.read_text(encoding="utf-8"))
    role = CHALLENGER if champion(MlflowClient(), args.model_name) else CHAMPION
    tags = {name: f"{value:.4f}" for name, value in report["metrics"].items()}
    tags |= {STAGE: role, "data_asset": args.data_asset, "pipeline_run": os.environ.get("AZUREML_ROOT_RUN_ID", "local")}
    version = register(args.model, args.model_name, tags)
    mlflow.log_params({"registered_version": version.version, STAGE: role})
    return f"{args.model_name}:{version.version} is the {role}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--model-name", default="readmission-risk")
    parser.add_argument("--data-asset", required=True)
    print(main(parser.parse_args()))
