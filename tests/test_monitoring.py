import inspect
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
from azure.ai.ml import MLClient

from src.data.synthesize import seed_cohort
from src.monitoring import drift as monitor


def test_drift_is_declared_only_when_enough_features_move() -> None:
    reference, current = seed_cohort(3000, np.random.default_rng(10)), seed_cohort(3000, np.random.default_rng(11))
    assert not monitor.drift(reference, current)["drift"], "two draws of the same population are not drift"
    moving = [name for name in current.columns if current[name].nunique() > 2 and name not in ("person_id",)]
    found = monitor.drift(reference, current.assign(**{name: current[name] * 1.5 + 1 for name in moving}))
    assert found["drift"] and found["share"] >= monitor.THRESHOLD and set(found["drifted"]) <= set(moving)


def test_drift_retrains_on_the_current_version_and_never_promotes() -> None:
    submitted: list[Any] = []

    def create(job: Any, experiment_name: str) -> SimpleNamespace:
        submitted.append(job)
        return SimpleNamespace(name="drift-run", studio_url="url")

    jobs = SimpleNamespace(create_or_update=create)
    client = cast(MLClient, SimpleNamespace(jobs=jobs))
    assert monitor.retrain(client, "2", "00000000-0000-0000-0000-000000000000") == "drift-run"
    assert submitted[0].tags == {"data_asset": "patient-cohort:2", "trigger": "drift"}
    assert submitted[0]._to_dict()["inputs"]["data_asset"] == "patient-cohort:2"
    source = inspect.getsource(monitor)
    assert not any(call in source for call in ("set_model_version_tag", ".traffic", "online_endpoints")), (
        "never promotes"
    )
