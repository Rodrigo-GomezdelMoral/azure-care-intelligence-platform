from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from mlflow.models import infer_signature

import api.main as api
from pipelines.scoring import call_list
from src.cohorts import what_worked
from src.components.prep import contract, encode, validate
from src.components.train import DEFAULTS, FAMILIES, features_of, model
from src.data.synthesize import LABEL, seed_cohort
from src.economics import Economics
from src.scoring import score
from src.scoring.score import Scorer, phrase


def test_every_explanation_sentence_is_a_fixed_template() -> None:
    assert phrase("pdc_180d", 0.52) == "took their medication on 52% of days over the last six months"
    assert phrase("has_caregiver", 0) == "has no caregiver" and phrase("lives_alone", 1) == "lives alone"
    assert (
        phrase("condition_heart_failure", 1) == "has heart failure"
        and phrase("drug_statin", 0) == "does not have statin"
    )
    assert phrase("portal_logins_90d", 3) == "has portal logins 90d of 3"


def test_the_scorer_returns_a_score_with_three_phrased_drivers_and_scores_files(tmp_path: Path) -> None:
    cohort = encode(validate(seed_cohort(1500, np.random.default_rng(8)), contract()))
    features = features_of(cohort, LABEL)
    pipeline = model(features, FAMILIES[0], DEFAULTS | {"max_iter": 40}, 7).fit(cohort[features], cohort[LABEL])
    signature = infer_signature(cohort[features].head(), pipeline.predict_proba(cohort[features].head())[:, 1])
    mlflow.sklearn.save_model(pipeline, str(tmp_path / "model"), signature=signature)
    score.SCORER = Scorer(tmp_path / "model")
    answer = score.run('{"patients": ' + cohort.head(2).to_json(orient="records") + "}")
    assert len(answer) == 2 and 0 <= answer[0]["score"] <= 1 and len(answer[0]["drivers"]) == 3
    assert answer[0]["person_id"] == int(cohort["person_id"].iloc[0]) and isinstance(answer[0]["person_id"], int)
    assert all(" the risk" in driver["text"] for driver in answer[0]["drivers"])
    assert set(score.SCORER.contributions(cohort.head(3)).columns) == set(features), "one-hot columns are summed back"
    cohort.head(10).to_parquet(tmp_path / "part.parquet", index=False)
    rows = score.run([str(tmp_path / "part.parquet")])
    assert list(rows.columns) == ["person_id", "score"] and len(rows) == 10


def test_the_call_list_ranks_pays_and_stops_at_capacity() -> None:
    scored = pd.DataFrame({"person_id": [1, 2, 3, 4], "score": [0.9, 0.01, 0.5, 0.7]})
    listed = call_list(scored, Economics(), capacity=2)
    assert listed["person_id"].tolist() == [1, 4] and listed["rank"].tolist() == [1, 2]
    assert listed["expected_value_eur"].tolist() == pytest.approx([1045.0, 805.0]), "priced by src/economics.py"
    assert call_list(scored, Economics(), capacity=10)["person_id"].tolist() == [1, 4, 3], (
        "below break-even is never called"
    )


def test_what_worked_compares_neighbours_with_and_without_care_manager_contact() -> None:
    columns = ["readmission_30d", "care_manager_contacts_12m", "pdc_180d", "has_caregiver"]
    rows = [(True, 0, 0.5, False), (False, 2, 0.9, True), (False, 1, 0.8, True), (True, 0, 0.4, False)]
    summary = what_worked(pd.DataFrame(rows, columns=columns))
    assert summary["readmission_rate_with_care_manager"] == 0.0 == 1 - summary["readmission_rate_without_care_manager"]
    assert summary["neighbours"] == 4 and summary["share_with_caregiver"] == 0.5


def test_the_api_demands_a_token_unless_a_local_run_turns_it_off() -> None:
    client, local = TestClient(api.app), api.Settings(require_auth=False)
    assert client.get("/healthz").json() == {"status": "ok"} and api.settings.require_auth and not local.require_auth
    assert client.get("/call-list").status_code == 401
    assert client.get("/call-list", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
