"""Composes the four components into the training pipeline and submits it on serverless compute.

A run records the data asset version, the component specs snapshotted with the code and the
parameters, so it can be reproduced (ADR-002 for the compute). `--sweep` replaces training by a
Bayesian sweep whose best trial feeds the same evaluation and gate; `--wait` streams the run so a
workflow fails when the pipeline does, and `--report` writes the summary a workflow publishes.
"""

import argparse
import os
from pathlib import Path
from typing import Any

import mlflow
from azure.ai.ml import Input, MLClient, load_component
from azure.ai.ml.dsl import pipeline
from azure.ai.ml.entities import JobResourceConfiguration, ManagedIdentityConfiguration, PipelineJob
from azure.ai.ml.sweep import Choice, Uniform

from ops.data_asset import ASSET, workspace
from src.components.train import DEFAULTS, FAMILIES
from src.economics import METRIC

COMPONENTS = Path(__file__).resolve().parents[1] / "src" / "components"
STEPS = ("prep", "train", "evaluate", "register")
EXPERIMENT, MODEL_NAME = "readmission-risk", "readmission-risk"
INSTANCE, CLUSTER, TRIALS, CONCURRENT = "Standard_DS3_v2", "cpu-cluster", 12, 3
PRIMARY_METRIC = f"validation_{METRIC}"
SPACE: dict[str, Any] = {"learning_rate": Uniform(0.02, 0.2), "max_iter": Choice([100, 200, 400])}
SPACE |= {"max_leaf_nodes": Choice([15, 31, 63]), "min_samples_leaf": Choice([10, 20, 50, 100])}
SPACE |= {"l2_regularization": Uniform(0.0, 1.0)}


def components() -> dict[str, Any]:
    return {name: load_component(source=str(COMPONENTS / f"{name}.yml")) for name in STEPS}


def serverless(node: Any) -> Any:
    """Serverless compute provisions one node of this size for the step and releases it afterwards."""
    node.resources = JobResourceConfiguration(instance_type=INSTANCE, instance_count=1)
    return node


def finish(step: dict[str, Any], prep: Any, train: Any, contact_share: float, gate: dict[str, Any]) -> dict[str, Any]:
    """evaluate on the test split, then the gate; the model, the report and the decision are the outputs."""
    evaluate = serverless(
        step["evaluate"](model=train.outputs.model, test=prep.outputs.test, contact_share=contact_share)
    )
    outputs = {"model": train.outputs.model, "metrics": evaluate.outputs.metrics}
    register = serverless(step["register"](**outputs, model_name=MODEL_NAME, **gate))
    return outputs | {"decision": register.outputs.decision}


def compose(
    cohort: Input,
    data_asset: str,
    family: str = FAMILIES[0],
    seed: int = 7,
    contact_share: float = 0.02,
    min_improvement: float = 0.0,
    learning_rate: float = 0.05,
    max_iter: int = 300,
    max_leaf_nodes: int = 31,
    min_samples_leaf: int = 20,
    l2_regularization: float = 0.0,
) -> dict[str, Any]:
    """prep, train, evaluate, register with one parameter set."""
    step = components()
    prep = serverless(step["prep"](cohort=cohort, seed=seed))
    params = {"learning_rate": learning_rate, "max_iter": max_iter, "max_leaf_nodes": max_leaf_nodes}
    params |= {"min_samples_leaf": min_samples_leaf, "l2_regularization": l2_regularization}
    splits = {"train": prep.outputs.train, "validation": prep.outputs.validation}
    train = serverless(step["train"](**splits, family=family, seed=seed, contact_share=contact_share, **params))
    return finish(step, prep, train, contact_share, {"data_asset": data_asset, "min_improvement": min_improvement})


def tune(
    cohort: Input, data_asset: str, seed: int = 7, contact_share: float = 0.02, min_improvement: float = 0.0
) -> dict[str, Any]:
    """The same pipeline with a Bayesian sweep over the gradient-boosting space as its training step."""
    step = components()
    prep = serverless(step["prep"](cohort=cohort, seed=seed))
    splits = {"train": prep.outputs.train, "validation": prep.outputs.validation}
    trial = step["train"](**splits, family=FAMILIES[0], seed=seed, contact_share=contact_share, **SPACE)
    train = trial.sweep(primary_metric=PRIMARY_METRIC, goal="maximize", sampling_algorithm="bayesian", compute=CLUSTER)
    train.set_limits(max_total_trials=TRIALS, max_concurrent_trials=CONCURRENT, trial_timeout=1800)
    return finish(step, prep, train, contact_share, {"data_asset": data_asset, "min_improvement": min_improvement})


training = pipeline(compose, name="training", display_name="Readmission risk training", default_compute="serverless")
tuning = pipeline(tune, name="tuning", display_name="Readmission risk tuning", default_compute="serverless")


def submit(client: MLClient, job: PipelineJob, identity: str, tags: dict[str, str], wait: bool) -> PipelineJob:
    """Steps run as the pipeline identity; serverless offers no system-assigned one and user tokens cannot pull.

    Command nodes carry it; a sweep node's identity is dropped by SDK and service alike (measured; see CLAUDE.md),
    so the trials run on the scale-to-zero cluster, whose own identity is the same `id-careaml`.
    """
    job.identity = ManagedIdentityConfiguration(client_id=identity)
    for node in job.jobs.values():
        node.identity = ManagedIdentityConfiguration(client_id=identity)
    job.tags = tags
    submitted: PipelineJob = client.jobs.create_or_update(job, experiment_name=EXPERIMENT)
    print(f"{submitted.name} {submitted.studio_url}")
    if wait:
        client.jobs.stream(submitted.name)
    return submitted


def report(client: MLClient, name: str) -> str:
    """Markdown for a public pull request or job summary: the run name, test metrics and gate decision, no ids."""
    mlflow.set_tracking_uri(client.workspaces.get(client.workspace_name).mlflow_tracking_uri)
    steps = {job.display_name: mlflow.get_run(job.name).data for job in client.jobs.list(parent_job_name=name)}
    metrics, gate = steps["evaluate"].metrics, steps["register"].params
    rows = [f"| {key} | {metrics[key]:,.3f} |" for key in (METRIC, "precision_at_capacity", "auc", "calibration_error")]
    head = [f"Training run `{name}` in the workspace", "", "| Test metric | Value |", "|---|---|"]
    verdict = f"Gate: **{gate.get('decision')}**, challenger {gate.get('challenger')} against {gate.get('champion')}"
    return "\n".join([*head, *rows, "", verdict])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-version", default="1")
    parser.add_argument("--family", choices=FAMILIES, default=FAMILIES[0])
    parser.add_argument("--contact-share", type=float, default=0.02)
    parser.add_argument("--min-improvement", type=float, default=0.0)
    parser.add_argument("--sweep", action="store_true")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--report", type=Path)
    for name, default in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=type(default), default=default)
    args = parser.parse_args()
    asset = f"{ASSET}:{args.data_version}"
    cohort = Input(type="uri_file", path=f"azureml:{asset}")
    policy = {"contact_share": args.contact_share, "min_improvement": args.min_improvement}
    if args.sweep:
        job = tuning(cohort=cohort, data_asset=asset, **policy)
    else:
        params = {name: getattr(args, name) for name in DEFAULTS}
        job = training(cohort=cohort, data_asset=asset, family=args.family, **policy, **params)
    tags = {"data_asset": asset, "family": "sweep" if args.sweep else args.family}
    client = workspace()
    submitted = submit(client, job, os.environ["AML_IDENTITY_CLIENT_ID"], tags, args.wait)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report(client, str(submitted.name)), encoding="utf-8")
