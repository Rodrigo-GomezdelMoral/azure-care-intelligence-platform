"""Composes the four components into the training pipeline and submits it on serverless compute.

Each run is reproducible from three things it records: the data asset version it read, the
component versions it ran (the YAML specs, snapshotted with the code) and the parameter set in
its inputs. Nothing exists between runs: no cluster, no node pool (ADR-002). `--wait` streams the
run, so a workflow fails when the pipeline does.
"""

import argparse
import os
from pathlib import Path
from typing import Any

from azure.ai.ml import Input, MLClient, load_component
from azure.ai.ml.dsl import pipeline
from azure.ai.ml.entities import JobResourceConfiguration, ManagedIdentityConfiguration, PipelineJob

from ops.data_asset import ASSET, workspace
from src.components.train import DEFAULTS, FAMILIES

COMPONENTS = Path(__file__).resolve().parents[1] / "src" / "components"
STEPS = ("prep", "train", "evaluate", "register")
EXPERIMENT, MODEL_NAME, INSTANCE = "readmission-risk", "readmission-risk", "Standard_DS3_v2"


def components() -> dict[str, Any]:
    return {name: load_component(source=str(COMPONENTS / f"{name}.yml")) for name in STEPS}


def serverless(node: Any) -> Any:
    """Serverless compute provisions one node of this size for the step and releases it afterwards."""
    node.resources = JobResourceConfiguration(instance_type=INSTANCE, instance_count=1)
    return node


def compose(
    cohort: Input,
    data_asset: str,
    family: str = FAMILIES[0],
    seed: int = 7,
    contact_share: float = 0.02,
    learning_rate: float = 0.05,
    max_iter: int = 300,
    max_leaf_nodes: int = 31,
    min_samples_leaf: int = 20,
    l2_regularization: float = 0.0,
) -> dict[str, Any]:
    """prep, train, evaluate, register; the model and the evaluation report are the pipeline's outputs."""
    step = components()
    prep = serverless(step["prep"](cohort=cohort, seed=seed))
    params = {"learning_rate": learning_rate, "max_iter": max_iter, "max_leaf_nodes": max_leaf_nodes}
    params |= {"min_samples_leaf": min_samples_leaf, "l2_regularization": l2_regularization}
    splits = {"train": prep.outputs.train, "validation": prep.outputs.validation}
    train = serverless(step["train"](**splits, family=family, seed=seed, contact_share=contact_share, **params))
    evaluate = serverless(
        step["evaluate"](model=train.outputs.model, test=prep.outputs.test, contact_share=contact_share)
    )
    outputs = {"model": train.outputs.model, "metrics": evaluate.outputs.metrics}
    serverless(step["register"](**outputs, model_name=MODEL_NAME, data_asset=data_asset))
    return outputs


training = pipeline(compose, name="training", display_name="Readmission risk training", default_compute="serverless")


def submit(client: MLClient, job: PipelineJob, identity: str, tags: dict[str, str], wait: bool) -> PipelineJob:
    """Steps run as the pipeline identity; serverless offers no system-assigned one and user tokens cannot pull."""
    for node in job.jobs.values():
        node.identity = ManagedIdentityConfiguration(client_id=identity)
    job.tags = tags
    submitted: PipelineJob = client.jobs.create_or_update(job, experiment_name=EXPERIMENT)
    print(f"{submitted.name} {submitted.studio_url}")
    if wait:
        client.jobs.stream(submitted.name)
    return submitted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-version", default="1")
    parser.add_argument("--family", choices=FAMILIES, default=FAMILIES[0])
    parser.add_argument("--contact-share", type=float, default=0.02)
    parser.add_argument("--wait", action="store_true")
    for name, default in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=type(default), default=default)
    args = parser.parse_args()
    asset = f"{ASSET}:{args.data_version}"
    params = {name: getattr(args, name) for name in DEFAULTS}
    cohort = Input(type="uri_file", path=f"azureml:{asset}")
    job = training(cohort=cohort, data_asset=asset, family=args.family, contact_share=args.contact_share, **params)
    submit(
        workspace(), job, os.environ["AML_IDENTITY_CLIENT_ID"], {"data_asset": asset, "family": args.family}, args.wait
    )
