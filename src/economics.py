"""The business metric: cost avoided per thousand patients contacted, under a capacity constraint.

A contact costs tens of euros and a readmission thousands, so a contact pays for itself above a
probability of a few percent (ADR-005); the binding constraint is the programme's capacity, which
makes the question a ranking one. Every policy is priced the same way: a rule says who is
contacted, `cost_avoided` says what that is worth, and `register` gates on it (ADR-003). The euro
parameters are modelling assumptions, read from the environment with the defaults of `.env.example`.
"""

import argparse
import os
from dataclasses import asdict, dataclass
from typing import Any, Self

import numpy as np
from sklearn.metrics import precision_recall_curve

METRIC = "cost_avoided_per_thousand"
VARIABLES = {"contact_cost": "CONTACT_COST_EUR", "readmission_cost": "READMISSION_COST_EUR"}
VARIABLES |= {"effectiveness": "INTERVENTION_EFFECTIVENESS"}
Array = np.ndarray[Any, Any]


@dataclass(frozen=True)
class Economics:
    """Euro parameters of the outreach programme; defaults are the ones in `.env.example`."""

    contact_cost: float = 35.0
    readmission_cost: float = 4800.0
    effectiveness: float = 0.25
    contact_share: float = 0.02

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> Self:
        return cls(**{name: getattr(args, name) for name in asdict(cls())})

    @classmethod
    def from_env(cls) -> Self:
        return cls(
            **{name: float(os.environ.get(variable, getattr(cls(), name))) for name, variable in VARIABLES.items()}
        )

    @property
    def break_even(self) -> float:
        """The readmission probability above which a contact pays for itself."""
        return self.contact_cost / (self.effectiveness * self.readmission_cost)

    def expected_value(self, scores: Array) -> Array:
        """Net euros expected from contacting each patient, given their readmission probability."""
        return np.asarray(scores, dtype=float) * self.effectiveness * self.readmission_cost - self.contact_cost


def arguments(parser: argparse.ArgumentParser) -> None:
    """The programme parameters as command-line options, shared by every component that prices a ranking."""
    for name, default in asdict(Economics()).items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=default)


def contacted(scores: Array, share: float) -> Array:
    """The capacity policy: a programme that can reach this share of the population contacts the highest-scored."""
    budget = max(1, round(len(scores) * share))
    chosen = np.zeros(len(scores), dtype=bool)
    chosen[np.argsort(-np.asarray(scores, dtype=float), kind="stable")[:budget]] = True
    return chosen


def cost_avoided(outcomes: Array, chosen: Array, economics: Economics) -> dict[str, float]:
    """What a set of contacts is worth: precision among them and net euros avoided per thousand contacts."""
    contacts, hits = int(chosen.sum()), float(np.asarray(outcomes, dtype=float)[chosen].sum())
    avoided = hits * economics.effectiveness * economics.readmission_cost - contacts * economics.contact_cost
    return {"contacts": contacts, "precision": hits / max(contacts, 1), METRIC: avoided / max(contacts, 1) * 1000}


def policies(outcomes: Array, scores: Array, economics: Economics) -> dict[str, dict[str, float]]:
    """Three ways to decide whom to contact, priced alike: capacity, break-even probability, F1-optimal threshold."""
    precision, recall, thresholds = precision_recall_curve(outcomes, scores)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-9)
    rules = {"capacity": contacted(scores, economics.contact_share), "break_even": scores > economics.break_even}
    rules |= {"f1_optimal": scores >= thresholds[int(np.argmax(f1))]}
    return {name: cost_avoided(outcomes, chosen, economics) for name, chosen in rules.items()}


def summary(outcomes: Array, scores: Array, economics: Economics) -> dict[str, float]:
    """The capacity policy priced: the headline numbers `evaluate` reports and `register` compares."""
    priced = cost_avoided(outcomes, contacted(scores, economics.contact_share), economics)
    return {"contacts": priced["contacts"], "precision_at_capacity": priced["precision"], METRIC: priced[METRIC]}
