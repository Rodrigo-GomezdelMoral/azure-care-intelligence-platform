"""The business metric: cost avoided per thousand patients contacted, under a capacity constraint.

A contact costs tens of euros, a readmission costs thousands, and a contact prevents a fraction
of the readmissions it reaches. The programme can contact a fixed share of the cohort, so the
question a medical director asks — which patients do I call, and what does it save — is a
ranking question, not a classification threshold. The scalar defined here is what `evaluate`
reports and what registration is gated on; phase 5 adds the expected-value threshold and the
ranked call list on top of the same parameters.
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


def arguments(parser: argparse.ArgumentParser) -> None:
    """The programme parameters as command-line options, shared by every component that prices a ranking."""
    for name, default in asdict(Economics()).items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=float, default=default)


def contacted(scores: Array, share: float) -> Array:
    """The patients a programme with this capacity contacts: the highest-scored share of the population."""
    budget = max(1, round(len(scores) * share))
    chosen = np.zeros(len(scores), dtype=bool)
    chosen[np.argsort(-scores, kind="stable")[:budget]] = True
    return chosen


def summary(outcomes: Array, scores: Array, economics: Economics) -> dict[str, float]:
    """Precision among the contacted patients and the net euros avoided per thousand contacts."""
    chosen = contacted(np.asarray(scores, dtype=float), economics.contact_share)
    contacts, hits = int(chosen.sum()), float(np.asarray(outcomes, dtype=float)[chosen].sum())
    avoided = hits * economics.effectiveness * economics.readmission_cost - contacts * economics.contact_cost
    return {"contacts": contacts, "precision_at_capacity": hits / contacts, METRIC: avoided / contacts * 1000}
