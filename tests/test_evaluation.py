import json
from argparse import Namespace
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from src.components.prep import contract, encode, validate
from src.components.register import CHALLENGER, CHAMPION, REJECTED, decide, main
from src.data.synthesize import LABEL, seed_cohort
from src.economics import METRIC, Economics, contacted, cost_avoided, policies
from src.fairness import MEASURES, SUBGROUPS, audit, disparities


def test_registration_is_refused_when_the_challenger_loses() -> None:
    assert decide(None, 875_000.0) == CHAMPION
    assert decide(875_000.0, 875_000.0) == REJECTED, "a tie has not earned a registration"
    assert decide(875_000.0, 875_001.0) == CHALLENGER
    assert decide(875_000.0, 880_000.0, min_improvement=10_000.0) == REJECTED


def test_the_register_component_refuses_a_losing_challenger_against_a_real_registry(tmp_path: Path) -> None:
    mlflow.set_tracking_uri(f"file:///{tmp_path.as_posix()}/mlruns")
    features = pd.DataFrame({"a": [0.1, 0.9, 0.2, 0.8], "b": [1.0, 0.0, 1.0, 0.0]})
    mlflow.sklearn.save_model(LogisticRegression().fit(features, [0, 1, 0, 1]), str(tmp_path / "model"))
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"metrics": {METRIC: 875_000.0, "auc": 0.75}}), encoding="utf-8")
    args = Namespace(model=tmp_path / "model", metrics=metrics, decision=tmp_path / "decision.json")
    args.model_name, args.data_asset, args.min_improvement = "gate-test", "patient-cohort:1", 0.0
    assert main(args)["decision"] == CHAMPION
    rejected = main(args)
    assert (
        rejected["decision"] == REJECTED
        and rejected["champion_version"] == "1"
        and "registered_version" not in rejected
    )
    assert json.loads(args.decision.read_text(encoding="utf-8"))["decision"] == REJECTED
    assert [str(v.version) for v in mlflow.MlflowClient().search_model_versions("name='gate-test'")] == ["1"]


def test_the_fairness_audit_covers_every_subgroup_with_parity_ratios() -> None:
    frame = encode(validate(seed_cohort(3000, np.random.default_rng(6)), contract()))
    outcomes = frame[LABEL].to_numpy()
    scores = np.clip(outcomes * 0.5 + np.random.default_rng(1).random(len(frame)) * 0.5, 0, 1)
    report = audit(frame, outcomes, scores, contacted(scores, 0.1))
    assert set(report) == set(SUBGROUPS) and set(report["sex"]["groups"]) == {"female", "male"}
    assert all(group["patients"] > 0 for attribute in report.values() for group in attribute["groups"].values())
    assert all(0 < attribute["disparity"][m] <= 1 for attribute in report.values() for m in MEASURES)
    assert len(disparities(report)) == len(SUBGROUPS) * len(MEASURES)
    flat = disparities(report)
    assert flat["disparity_sex_selection_rate"] == report["sex"]["disparity"]["selection_rate"]


def test_a_contact_pays_for_itself_above_a_few_percent_and_any_policy_is_priced_alike() -> None:
    economics = Economics(contact_share=0.2)
    assert economics.break_even == pytest.approx(35 / (0.25 * 4800))
    assert economics.expected_value(np.array([0.01]))[0] < 0 < economics.expected_value(np.array([0.5]))[0]
    outcomes, scores = np.array([1, 1, 0, 0, 0, 0, 0, 0, 0, 0]), np.linspace(1, 0, 10)
    by_threshold = cost_avoided(outcomes, scores > economics.break_even, economics)
    by_capacity = cost_avoided(outcomes, contacted(scores, 0.2), economics)
    assert by_capacity[METRIC] > by_threshold[METRIC] and by_threshold["contacts"] == 9
    priced = policies(outcomes, scores, economics)
    assert set(priced) == {"capacity", "break_even", "f1_optimal"} and priced["capacity"] == by_capacity
    assert priced["f1_optimal"]["contacts"] == 2, "the F1 optimum on a perfect ranking is the two positives"


def test_the_programme_parameters_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTACT_COST_EUR", "50")
    assert (
        Economics.from_env() == Economics(contact_cost=50.0)
        and Economics.from_env().break_even > Economics().break_even
    )
