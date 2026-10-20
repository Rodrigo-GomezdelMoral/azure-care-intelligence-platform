from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
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
    assert list(rows.columns) == ["person_id", "score", "expected_value_eur"] and len(rows) == 10


def test_the_call_list_ranks_pays_and_stops_at_capacity() -> None:
    scored = pd.DataFrame(
        {"person_id": [1, 2, 3, 4], "score": [0.9, 0.01, 0.5, 0.7], "expected_value_eur": [1045.0, -23.0, 565.0, 805.0]}
    )
    listed = call_list(scored, Economics(), capacity=2)
    assert listed["person_id"].tolist() == [1, 4] and listed["rank"].tolist() == [1, 2]
    assert call_list(scored, Economics(), capacity=10)["person_id"].tolist() == [1, 4, 3], (
        "below break-even is never called"
    )


def test_what_worked_compares_neighbours_with_and_without_care_manager_contact() -> None:
    neighbours = pd.DataFrame(
        {
            "readmission_30d": [True, False, False, True],
            "care_manager_contacts_12m": [0, 2, 1, 0],
            "pdc_180d": [0.5, 0.9, 0.8, 0.4],
            "has_caregiver": [False, True, True, False],
        }
    )
    summary = what_worked(neighbours)
    assert (
        summary["readmission_rate_with_care_manager"] == 0.0 and summary["readmission_rate_without_care_manager"] == 1.0
    )
    assert summary["neighbours"] == 4 and summary["share_with_caregiver"] == 0.5


def test_the_api_is_open_locally_and_demands_a_token_otherwise() -> None:
    client = TestClient(api.app)
    assert client.get("/healthz").json() == {"status": "ok"}
    api.settings.require_auth = True
    try:
        assert client.get("/call-list").status_code == 401
        assert client.get("/call-list", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    finally:
        api.settings.require_auth = False
