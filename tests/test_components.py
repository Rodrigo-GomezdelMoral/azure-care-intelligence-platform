from types import SimpleNamespace
from typing import cast

import numpy as np
import pandas as pd
import pytest
from azure.ai.ml import Input
from mlflow import MlflowClient

from pipelines.training import INSTANCE, PRIMARY_METRIC, SPACE, STEPS, TRIAL_INSTANCE, training, tuning
from src.components.evaluate import evaluate
from src.components.prep import SchemaDriftError, contract, encode, split, validate
from src.components.register import CHALLENGER, CHAMPION, STAGE, champion
from src.components.train import DEFAULTS, FAMILIES, features_of, fit
from src.data.synthesize import LABEL, seed_cohort
from src.economics import METRIC, Economics, summary


@pytest.fixture(scope="module")
def cohort() -> pd.DataFrame:
    return encode(validate(seed_cohort(4000, np.random.default_rng(4)), contract()))


def test_prep_fails_loudly_on_schema_drift() -> None:
    frame, schema = seed_cohort(200, np.random.default_rng(5)), contract()
    assert validate(frame, schema).columns.tolist() == list(schema["columns"])
    assert validate(frame.assign(age=frame["age"].astype(int)), schema) is not None, "numeric widening is not drift"
    with pytest.raises(SchemaDriftError, match='"missing": \\["pdc_180d"\\]'):
        validate(frame.drop(columns=["pdc_180d"]), schema)
    with pytest.raises(SchemaDriftError, match='"wrong_type": \\["age"\\]'):
        validate(frame.assign(age=frame["age"].astype(str)), schema)
    with pytest.raises(SchemaDriftError, match='"mostly_empty": \\["measurement_ldl"\\]'):
        validate(frame.assign(measurement_ldl=np.nan), schema)


def test_prep_split_is_stratified_and_disjoint(cohort: pd.DataFrame) -> None:
    parts = split(cohort, LABEL, 7)
    assert [len(part) for part in parts.values()] == [2800, 600, 600]
    ids = [set(part["person_id"]) for part in parts.values()]
    assert not (ids[0] & ids[1]) and not (ids[1] & ids[2]) and not (ids[0] & ids[2])
    rates = [part[LABEL].mean() for part in parts.values()]
    assert max(rates) - min(rates) < 0.01
    assert all(dtype.kind in "if" for dtype in cohort.dtypes), "booleans were encoded as integers"


def test_train_fits_one_pipeline_with_preprocessing_inside(cohort: pd.DataFrame) -> None:
    parts = split(cohort, LABEL, 7)
    params = DEFAULTS | {"max_iter": 60}
    pipeline, metrics = fit(parts["train"], parts["validation"], FAMILIES[0], params, 7, Economics())
    assert metrics["validation_auc"] > 0.7 and metrics[f"validation_{METRIC}"] > 0
    assert [name for name, _ in pipeline.steps] == ["preprocess", "classifier"]
    probe = parts["test"][features_of(parts["test"], LABEL)].head(3).copy()
    probe.loc[probe.index[0], "measurement_ldl"] = np.nan
    probe.loc[probe.index[1], "urbanicity"] = 9
    assert pipeline.predict_proba(probe).shape == (3, 2), "missing values and unseen levels are handled by the model"


def test_evaluate_reports_calibration_and_euros(cohort: pd.DataFrame) -> None:
    outcomes = cohort[LABEL].to_numpy()
    oracle = SimpleNamespace(predict_proba=lambda frame: np.column_stack([1 - outcomes, outcomes]))
    report = evaluate(oracle, cohort, Economics())
    metrics = report["metrics"]
    assert metrics["auc"] == 1.0 and metrics["precision_at_capacity"] == 1.0 and metrics["calibration_error"] < 1e-9
    assert metrics[METRIC] == pytest.approx(0.25 * 4800 * 1000 - 35 * 1000) and metrics["contacts"] == 80
    assert len(report["calibration"]) == 10 and metrics["patients"] == 4000


def test_cost_avoided_rewards_the_ranking_at_capacity() -> None:
    outcomes = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    good, bad = np.linspace(1, 0, 10), np.linspace(0, 1, 10)
    economics = Economics(contact_share=0.2)
    assert summary(outcomes, good, economics)[METRIC] > 0 > summary(outcomes, bad, economics)[METRIC]
    assert summary(outcomes, good, economics)["contacts"] == 2


def test_the_first_registered_version_is_the_champion_and_the_next_a_challenger() -> None:
    versions = [SimpleNamespace(version="1", tags={STAGE: CHAMPION}), SimpleNamespace(version="2", tags={})]
    stub = SimpleNamespace(search_model_versions=lambda query: versions if "readmission" in query else [])
    registry = cast(MlflowClient, stub)
    first = champion(registry, "readmission-risk")
    assert first is not None and first.version == "1" and champion(registry, "other-model") is None
    assert (CHALLENGER if first else CHAMPION) == CHALLENGER


def test_the_pipeline_composes_the_four_components_offline() -> None:
    job = training(cohort=Input(type="uri_file", path="azureml:patient-cohort:1"), data_asset="patient-cohort:1")
    assert list(job.jobs) == list(STEPS) and job._to_dict()["settings"]["default_compute"] == "serverless"
    assert all(job.jobs[name].resources.instance_type == INSTANCE for name in STEPS)
    wiring = job._to_dict()["jobs"]
    assert wiring["train"]["inputs"]["train"]["path"] == "${{parent.jobs.prep.outputs.train}}"
    assert wiring["evaluate"]["inputs"]["model"]["path"] == "${{parent.jobs.train.outputs.model}}"
    assert wiring["register"]["inputs"]["metrics"]["path"] == "${{parent.jobs.evaluate.outputs.metrics}}"
    assert set(job._to_dict()["outputs"]) == {"model", "metrics", "decision"}


def test_the_tuning_pipeline_sweeps_the_metric_that_train_logs() -> None:
    job = tuning(cohort=Input(type="uri_file", path="azureml:patient-cohort:1"), data_asset="patient-cohort:1")
    sweep = job._to_dict()["jobs"]["train"]
    assert sweep["type"] == "sweep" and sweep["sampling_algorithm"] == "bayesian"
    assert sweep["objective"] == {"goal": "maximize", "primary_metric": PRIMARY_METRIC}
    assert set(sweep["search_space"]) == set(SPACE) and sweep["resources"]["instance_type"] == TRIAL_INSTANCE
    logged = {f"validation_{name}" for name in summary(np.array([1, 0]), np.array([0.9, 0.1]), Economics())}
    assert PRIMARY_METRIC in logged, "the sweep optimises nothing unless the name matches what train logs"
    assert job._to_dict()["jobs"]["evaluate"]["inputs"]["model"]["path"] == "${{parent.jobs.train.outputs.model}}"
