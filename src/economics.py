"""The business metric: cost avoided per thousand patients contacted, under a capacity constraint.

A contact costs tens of euros, a readmission costs thousands, and a contact prevents a fraction
of the readmissions it reaches, so contacting a patient has positive expected value above a
probability of only a few percent (ADR-005). The binding constraint is the programme's capacity,
and the question a medical director asks (which patients do I call, and what does it save) is a
ranking question, not a classification threshold. Every policy in this repository is priced the
same way: a rule says who is contacted, and `cost_avoided` says what that set of contacts is
worth; `register` gates on that number (ADR-003).
"""

import argparse
from dataclasses import asdict, dataclass
from typing import Any, Self

import numpy as np

METRIC = "cost_avoided_per_thousand"
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


def summary(outcomes: Array, scores: Array, economics: Economics) -> dict[str, float]:
    """The capacity policy priced: the headline numbers `evaluate` reports and `register` compares."""
    priced = cost_avoided(outcomes, contacted(scores, economics.contact_share), economics)
    return {"contacts": priced["contacts"], "precision_at_capacity": priced["precision"], METRIC: priced[METRIC]}
