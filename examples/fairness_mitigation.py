"""Experiment 003: what closing a subgroup gap at the operating point costs in cost avoided.

Reproduces experiments/003-fairness-mitigation.md from the splits `prep` writes for data asset
`patient-cohort:1` with seed 7 and the champion model downloaded from the registry:

    python examples/fairness_mitigation.py --train train.parquet --test test.parquet --model model/

Never imported by the system; it reads the same modules the pipeline runs.
"""

import argparse
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd

from src.components.prep import IDENTIFIER, contract
from src.components.train import DEFAULTS, FAMILIES, model
from src.economics import METRIC, Economics, contacted, cost_avoided
from src.fairness import SUBGROUPS, audit

ATTRIBUTE = "insurance"


def quota(scores: np.ndarray, groups: np.ndarray, share: float) -> np.ndarray:
    """Need-proportional allocation: each group gets contacts in proportion to its expected readmissions."""
    budget, chosen = max(1, round(len(scores) * share)), np.zeros(len(scores), dtype=bool)
    need = {g: scores[groups == g].sum() for g in np.unique(groups)}
    seats = {g: int(round(budget * n / sum(need.values()))) for g, n in need.items()}
    for group, count in seats.items():
        members = np.flatnonzero(groups == group)
        chosen[members[np.argsort(-scores[members], kind="stable")[:count]]] = True
    return chosen


def row(name: str, test: pd.DataFrame, outcomes: np.ndarray, scores: np.ndarray, chosen: np.ndarray) -> dict:
    report, priced = audit(test, outcomes, scores, chosen), cost_avoided(outcomes, chosen, Economics())
    groups = report[ATTRIBUTE]["groups"]
    result = {"variant": name, "contacts": priced["contacts"], "precision": round(priced["precision"], 3)}
    result |= {METRIC: round(priced[METRIC]), "recall_parity_insurance": round(report[ATTRIBUTE]["disparity"]["recall"], 3)}
    result |= {f"recall_{g}": round(m["recall"], 3) for g, m in groups.items()}
    return result | {"selection_parity_age": round(report["age_band"]["disparity"]["selection_rate"], 3)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--test", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    label, share = contract()["label"], Economics().contact_share
    train, test = pd.read_parquet(args.train), pd.read_parquet(args.test)
    features = [c for c in test.columns if c not in (label, IDENTIFIER)]
    outcomes = test[label].to_numpy()
    champion = mlflow.sklearn.load_model(str(args.model)).predict_proba(test[features])[:, 1]
    groups = SUBGROUPS[ATTRIBUTE](test).astype(str).to_numpy()
    ages = SUBGROUPS["age_band"](test).astype(str).to_numpy()
    unaware = [c for c in features if c != "insurance_type"]
    blind = model(unaware, FAMILIES[0], DEFAULTS, 7).fit(train[unaware], train[label]).predict_proba(test[unaware])[:, 1]
    rows = [
        row("champion, top 2 %", test, outcomes, champion, contacted(champion, share)),
        row("champion, need-proportional quota by insurance", test, outcomes, champion, quota(champion, groups, share)),
        row("retrained without insurance_type, top 2 %", test, outcomes, blind, contacted(blind, share)),
        row("champion, need-proportional quota by age band", test, outcomes, champion, quota(champion, ages, share)),
    ]
    print(pd.DataFrame(rows).to_markdown(index=False))
