"""Subgroup audit of the ranking at its operating point: who gets contacted, and who is missed.

A score that ranks well on average can still reach one group less often than its need warrants,
so the audit looks at the contacted set the programme acts on, not at the probabilities. For
every subgroup of each protected attribute it reports the patients and their readmission rate,
the share contacted (selection rate), the share of its readmitted patients contacted (recall,
the equal-opportunity measure), the precision among its contacts (predictive parity) and the
group's own AUC. The disparity of a measure is the ratio of its lowest to its highest group
value, so 1.0 is parity; the model card quotes the worst one and experiment 003 what closing it
costs. The disparities this finds on synthetic data are the ones the generator induces (ADR-008).
"""

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

Array = np.ndarray[Any, Any]
AGE_BANDS, DEPRIVATION_BANDS = [0, 64, 74, 200], [-1, 3, 6, 10]
SUBGROUPS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "sex": lambda f: f["gender_concept_id"].map({8507: "male", 8532: "female"}),
    "language_barrier": lambda f: f["language_barrier"].map({0: "no", 1: "yes"}),
    "age_band": lambda f: pd.cut(f["age"], AGE_BANDS, labels=["under_65", "65_to_74", "75_plus"]),
    "deprivation": lambda f: pd.cut(f["deprivation_index"], DEPRIVATION_BANDS, labels=["low", "medium", "high"]),
    "insurance": lambda f: f["insurance_type"].map({0: "public", 1: "private", 2: "none"}),
}
MEASURES = ("selection_rate", "recall", "precision")


def group_metrics(outcomes: Array, scores: Array, chosen: Array) -> dict[str, float]:
    positives = outcomes.astype(bool)
    mixed = 0 < positives.sum() < len(outcomes)
    return {
        "patients": len(outcomes),
        "readmission_rate": float(positives.mean()),
        "auc": float(roc_auc_score(outcomes, scores)) if mixed else float("nan"),
        "selection_rate": float(chosen.mean()),
        "recall": float(chosen[positives].mean()) if positives.any() else float("nan"),
        "precision": float(positives[chosen].mean()) if chosen.any() else float("nan"),
    }


def parity_ratio(values: list[float]) -> float:
    low, high = np.nanmin(values), np.nanmax(values)
    return float(low / high) if high > 0 else float("nan")


def audit(frame: pd.DataFrame, outcomes: Array, scores: Array, chosen: Array) -> dict[str, Any]:
    """Per-subgroup table and the parity ratio of every measure, for each protected attribute."""
    report: dict[str, Any] = {}
    for attribute, labels_of in SUBGROUPS.items():
        labels = labels_of(frame).astype(str).to_numpy()
        groups = {
            label: group_metrics(outcomes[labels == label], scores[labels == label], chosen[labels == label])
            for label in sorted(set(labels))
        }
        disparity = {measure: parity_ratio([group[measure] for group in groups.values()]) for measure in MEASURES}
        report[attribute] = {"groups": groups, "disparity": disparity}
    return report


def disparities(report: dict[str, Any]) -> dict[str, float]:
    """The parity ratios as flat MLflow metric names: disparity_<attribute>_<measure>."""
    return {f"disparity_{a}_{m}": float(r["disparity"][m]) for a, r in report.items() for m in MEASURES}
