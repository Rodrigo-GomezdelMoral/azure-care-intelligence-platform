"""Creates or updates the serving endpoints: one online (blue/green), one batch, both Entra-only.

The online endpoint answers one patient at a time with an explanation; the batch endpoint scores
the whole cohort for the weekly list. Both run the same scoring module from the same registered
model version with the pipeline identity `id-careaml`, so images, models and data are reached
without a key. Traffic between blue and green is a parameter: the deployment workflow shifts 10 %
and then 100 % after its smoke check (ADR-004). The batch deployment runs on the scale-to-zero
cluster, the one compute this repository keeps (ADR-002).
"""

import argparse
import os
from typing import Any

import mlflow
from azure.ai.ml import MLClient
from azure.ai.ml import entities as ml

from ops.data_asset import workspace
from src.components.register import CHAMPION, STAGE

CODE = ml.CodeConfiguration(code="src/scoring", scoring_script="score.py")
IMAGE, INSTANCE, CLUSTER = "mcr.microsoft.com/azureml/openmpi4.1.0-ubuntu22.04", "Standard_DS2_v2", "cpu-cluster"
BATCH_SETTINGS: dict[str, Any] = {"compute": CLUSTER, "instance_count": 1, "max_concurrency_per_instance": 1}
BATCH_SETTINGS |= {"mini_batch_size": 1, "output_action": "append_row", "output_file_name": "predictions.csv"}
BATCH_SETTINGS |= {"retry_settings": ml.BatchRetrySettings(max_retries=1, timeout=900)}


def champion_version(client: MLClient, name: str) -> str:
    mlflow.set_tracking_uri(client.workspaces.get(client.workspace_name).mlflow_tracking_uri)
    versions = mlflow.MlflowClient().search_model_versions(f"name='{name}'")
    return str(next(v.version for v in versions if v.tags.get(STAGE) == CHAMPION))


def online(client: MLClient, shared: dict[str, Any], identity: str, name: str, traffic: int) -> str:
    """Endpoint with the pipeline identity, one more deployment (a failed one is recreated) and its traffic share."""
    endpoint_name = os.environ["ONLINE_ENDPOINT"]
    owner = ml.IdentityConfiguration(
        type="user_assigned", user_assigned_identities=[ml.ManagedIdentityConfiguration(resource_id=identity)]
    )
    client.online_endpoints.begin_create_or_update(
        ml.ManagedOnlineEndpoint(name=endpoint_name, auth_mode="aad_token", identity=owner)
    ).result()
    states = {d.name: d.provisioning_state for d in client.online_deployments.list(endpoint_name)}
    if states.get(name) == "Failed":
        client.online_deployments.begin_delete(name=name, endpoint_name=endpoint_name).result()
    deployment = ml.ManagedOnlineDeployment(
        name=name, endpoint_name=endpoint_name, instance_type=INSTANCE, instance_count=1, **shared
    )
    client.online_deployments.begin_create_or_update(deployment).result()
    endpoint = client.online_endpoints.get(endpoint_name)
    others = {d.name for d in client.online_deployments.list(endpoint_name)} - {name}
    endpoint.traffic = {name: traffic} | dict.fromkeys(others, 100 - traffic)
    return str(client.online_endpoints.begin_create_or_update(endpoint).result().scoring_uri)


def batch(client: MLClient, shared: dict[str, Any]) -> str:
    """Endpoint plus the `weekly` deployment on the cluster, appending one row per patient to predictions.csv."""
    endpoint_name = os.environ["BATCH_ENDPOINT"]
    client.batch_endpoints.begin_create_or_update(ml.BatchEndpoint(name=endpoint_name, auth_mode="aad_token")).result()
    deployment = ml.BatchDeployment(name="weekly", endpoint_name=endpoint_name, **shared, **BATCH_SETTINGS)
    client.batch_deployments.begin_create_or_update(deployment).result()
    endpoint = client.batch_endpoints.get(endpoint_name)
    endpoint.defaults.deployment_name = "weekly"
    return str(client.batch_endpoints.begin_create_or_update(endpoint).result().scoring_uri)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true")
    parser.add_argument("--batch", action="store_true")
    parser.add_argument("--deployment", default="blue")
    parser.add_argument("--traffic", type=int, default=100)
    parser.add_argument("--model-version")
    args, env, client = parser.parse_args(), os.environ, workspace()
    version = args.model_version or champion_version(client, env["MODEL_NAME"])
    serving = ml.Environment(name="careintel-serving", image=IMAGE, conda_file="src/scoring/conda.yml")
    shared = {"model": f"azureml:{env['MODEL_NAME']}:{version}", "code_configuration": CODE}
    shared |= {"environment": client.environments.create_or_update(serving)}
    scope = f"/subscriptions/{env['AZURE_SUBSCRIPTION_ID']}/resourceGroups/{env['AZURE_RESOURCE_GROUP']}"
    identity = f"{scope}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-careaml"
    if args.online:
        print("online:", online(client, shared, identity, args.deployment, args.traffic))
    if args.batch:
        print("batch:", batch(client, shared))
