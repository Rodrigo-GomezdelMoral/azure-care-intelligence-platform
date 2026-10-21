"""Scores patients and explains every score with SHAP contributions translated into plain language.

Online, patients arrive as JSON and each answer carries the probability and the three strongest
SHAP drivers in log-odds, summed back to raw columns and phrased by fixed templates keyed by
feature (ADR-012), so the same patient always gets the same words. In batch, a mini-batch of
parquet files becomes one score per patient; the call list prices them with `src/economics.py`.
The module imports nothing from the repository, so its deployment snapshot is this folder alone.
"""

import json
import os
from pathlib import Path
from typing import Any

import mlflow
import numpy as np
import pandas as pd
import shap

IDENTIFIER, TOP = "person_id", 3
TEMPLATES = {
    "pdc_180d": "took their medication on {value:.0%} of days over the last six months",
    "pdc_90d": "took their medication on {value:.0%} of days over the last three months",
    "charlson_index": "has a Charlson comorbidity index of {value:.0f}",
    "inpatient_admissions_12m": "had {value:.0f} hospital admission(s) in the last twelve months",
    "emergency_visits_12m": "had {value:.0f} emergency visit(s) in the last twelve months",
    "missed_appointments_12m": "missed {value:.0f} appointment(s) in the last twelve months",
    "age": "is {value:.0f} years old",
    "deprivation_index": "lives in an area scoring {value:.1f} of 10 on deprivation",
    "drug_era_count": "is prescribed {value:.0f} different medications",
    "copay_mean_eur": "pays {value:.0f} € of copay per prescription on average",
    "care_manager_contacts_12m": "had {value:.0f} care-manager contact(s) in the last twelve months",
}
FLAGS = {"has_caregiver": ("has no caregiver", "has a caregiver"), "lives_alone": ("lives with others", "lives alone")}
FLAGS |= {"language_barrier": ("speaks the care team's language", "faces a language barrier")}
FLAGS |= {"prior_readmission": ("was not readmitted before", "was readmitted before")}


def phrase(feature: str, value: float) -> str:
    """The deterministic sentence fragment for one feature value; never a language model."""
    if feature in TEMPLATES:
        return TEMPLATES[feature].format(value=value)
    if feature in FLAGS:
        return FLAGS[feature][int(bool(value))]
    name = feature.removeprefix("condition_").removeprefix("drug_").replace("_", " ")
    if feature.startswith(("condition_", "drug_")):
        return f"has {name}" if value else f"does not have {name}"
    return f"has {name} of {value:g}"


def driver(feature: str, value: Any, contribution: float) -> dict[str, Any]:
    text = f"{phrase(feature, float(value))}, which {'raises' if contribution > 0 else 'lowers'} the risk"
    return {"feature": feature, "contribution": round(contribution, 4), "text": text}


class Scorer:
    """A fitted pipeline, its explainer and the feature list the model signature declares."""

    def __init__(self, path: Path) -> None:
        self.model = mlflow.sklearn.load_model(str(path))
        self.features: list[str] = mlflow.models.Model.load(path).signature.inputs.input_names()
        self.explainer = shap.TreeExplainer(self.model.named_steps["classifier"])

    def scores(self, frame: pd.DataFrame) -> Any:
        return np.asarray(self.model.predict_proba(frame[self.features])[:, 1], dtype=float)

    def contributions(self, frame: pd.DataFrame) -> pd.DataFrame:
        """SHAP values on the preprocessed features, summed back to the raw columns."""
        preprocess = self.model.named_steps["preprocess"]
        matrix = preprocess.transform(frame[self.features])
        values = self.explainer.shap_values(matrix.toarray() if hasattr(matrix, "toarray") else matrix)
        raw = [name.split("__", 1)[1] for name in preprocess.get_feature_names_out()]
        raw = [column if column in self.features else column.rsplit("_", 1)[0] for column in raw]
        return pd.DataFrame(np.asarray(values), columns=raw, index=frame.index).T.groupby(level=0).sum().T

    def explain(self, frame: pd.DataFrame) -> list[dict[str, Any]]:
        """Score and the three strongest drivers, phrased, per patient."""
        scores, shaps = self.scores(frame), self.contributions(frame)
        matrix, names, answers = shaps.to_numpy(dtype=float), list(shaps.columns), []
        ids = frame[IDENTIFIER].tolist() if IDENTIFIER in frame else [None] * len(frame)
        for position, (_, row) in enumerate(frame.iterrows()):
            order = np.argsort(-np.abs(matrix[position]))[:TOP]
            answer = {IDENTIFIER: ids[position], "score": round(float(scores[position]), 4)}
            answers.append(
                answer | {"drivers": [driver(names[i], row[names[i]], float(matrix[position][i])) for i in order]}
            )
        return answers

    def batch(self, files: list[str]) -> pd.DataFrame:
        """One row per patient across the files of a mini-batch: identifier and score."""
        frame = pd.concat([pd.read_parquet(file) for file in files], ignore_index=True)
        return pd.DataFrame({IDENTIFIER: frame[IDENTIFIER], "score": self.scores(frame)})


SCORER: Scorer


def init() -> None:
    global SCORER
    SCORER = Scorer(next(Path(os.environ["AZUREML_MODEL_DIR"]).rglob("MLmodel")).parent)


def run(payload: Any) -> Any:
    """Online: a JSON document {"patients": [...]}; batch: the list of files of a mini-batch."""
    return (
        SCORER.batch(payload)
        if isinstance(payload, list)
        else SCORER.explain(pd.DataFrame(json.loads(payload)["patients"]))
    )
