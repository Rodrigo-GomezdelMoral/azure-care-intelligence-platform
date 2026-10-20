"""Synthetic chronic-care cohort. No real patient was used, seen or approximated.

A documented causal structure (ADR-008) draws a seed population from published adherence and
readmission distributions, one feature per line in causal order. CTGAN learns only the root
layer (sex, age, urbanicity, deprivation, language, employment, insurance) and samples it under
the documented categorical marginals; everything with a parent in the graph, the label included,
is recomputed by the same equations, so the signal a model finds is the one the equations put
there. Clinical columns follow OMOP CDM naming.
"""

import argparse
import itertools
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROWS, SEED_ROWS, EPOCHS, SEED = 40_000, 8_000, 30, 7
DATA = Path(__file__).resolve().parents[2] / "data"
LABEL = "readmission_30d"
CONDITIONS = {"type2_diabetes": (0.42, 1), "hypertension": (0.61, 0), "copd": (0.18, 1), "heart_failure": (0.14, 2)}
CONDITIONS |= {"ckd": (0.16, 2), "depression": (0.21, 1), "atrial_fibrillation": (0.09, 1), "obesity": (0.37, 0)}
CONDITIONS |= {"asthma": (0.08, 1), "cancer": (0.06, 2)}
DRUGS = [("insulin", "type2_diabetes", 0.35), ("anticoagulant", "atrial_fibrillation", 0.8)]
DRUGS += [("antidepressant", "depression", 0.7)]
ROLES = {"demographic": ("gender", "age", "year_of", "urban"), "comorbidity": ("condition_", "charlson")}
ROLES |= {"measurement": ("measurement_",), "outcome": ("readmission",), "person": ("person_id",)}
ROLES |= {"prescription": ("drug_", "pdc_", "adherent", "days_supply", "generic", "copay", "pharmacy", "prescriber")}
ROLES["prescription"] += ("high_risk", "refill", "polyph")
ROLES |= {"contact": ("inpatient", "emergency", "visit", "days_since", "missed", "telehealth", "care_manager")}
ROLES["contact"] += ("portal", "observation", "prior")
MARGINALS: dict[str, dict[Any, float]] = {"gender_concept_id": {8507: 0.48, 8532: 0.52}}
MARGINALS |= {"language_barrier": {False: 0.92, True: 0.08}, "urbanicity": {0: 0.25, 1: 0.45, 2: 0.30}}
MARGINALS |= {"employment_status": {0: 0.55, 1: 0.30, 2: 0.15}, "insurance_type": {0: 0.60, 1: 0.30, 2: 0.10}}


def roots(f: pd.DataFrame, rng: np.random.Generator) -> None:
    rows = len(f)
    for column, levels in MARGINALS.items():
        f[column] = rng.choice(list(levels), rows, p=list(levels.values()))
    f["age"] = np.clip(rng.normal(67, 11, rows), 40, 95).round()
    f["deprivation_index"] = (rng.beta(2, 3, rows) * 10).round(2)


def household(f: pd.DataFrame, rng: np.random.Generator) -> None:
    rows, strain = len(f), f["deprivation_index"]
    f["year_of_birth"] = 2026 - f["age"]
    f["income_quintile"] = np.clip(5 - (strain / 2.5).round(), 1, 5).astype(int)
    f["education_years"] = np.clip(rng.normal(12 - strain / 5, 2.5, rows), 6, 20).round()
    f["lives_alone"] = rng.random(rows) < 0.25 + 0.15 * (f["age"] > 75)
    f["has_caregiver"] = rng.random(rows) < 0.55 - 0.03 * strain
    f["distance_to_pharmacy_km"] = rng.lognormal(1.0, 0.7, rows).round(1)
    f["transport_access"] = rng.random(rows) < 0.85 - 0.04 * strain


def conditions(f: pd.DataFrame, rng: np.random.Generator) -> None:
    for name, (prevalence, _) in CONDITIONS.items():
        f[f"condition_{name}"] = rng.random(len(f)) < np.clip(prevalence * (1 + 0.012 * (f["age"] - 65)), 0.02, 0.95)


def drugs(f: pd.DataFrame, rng: np.random.Generator) -> None:
    rows, strain = len(f), f["deprivation_index"]
    weights = sum(f[f"condition_{n}"] * w for n, (_, w) in CONDITIONS.items())
    f["charlson_index"] = weights + (f["age"] > 70) + (f["age"] > 80)
    drugs = rng.poisson(1.5 + 0.9 * f["charlson_index"], rows) + 1
    f["drug_era_count"], f["polypharmacy"] = drugs, drugs >= 5
    f["drug_count_active"] = np.minimum(drugs, rng.poisson(drugs, rows) + 1)
    f["days_supply_mean"] = rng.choice([30, 60, 90], rows, p=[0.55, 0.25, 0.2])
    f["generic_share"] = rng.beta(5, 2, rows).round(2)
    f["copay_mean_eur"] = (rng.lognormal(2.3, 0.6, rows) * (1 + strain / 10)).round(1)
    f["pharmacy_count"] = rng.poisson(1.2, rows) + 1
    f["prescriber_count"] = np.minimum(rng.poisson(1.8, rows) + 1, drugs)
    f["high_risk_drug_count"] = rng.binomial(drugs, 0.18)
    for drug, condition, share in DRUGS:
        f[f"drug_{drug}"] = f[f"condition_{condition}"] & (rng.random(rows) < share)
    f["drug_statin"] = rng.random(rows) < 0.3 + 0.4 * f["condition_type2_diabetes"]
    f["refill_gap_days_mean"] = rng.gamma(2, 4, rows).round(1)
    f["care_manager_contacts_12m"] = rng.poisson(0.6 + 0.1 * strain, rows)


def adherence_and_contacts(f: pd.DataFrame, rng: np.random.Generator) -> None:
    rows, strain = len(f), f["deprivation_index"]
    logit = 1.6 - 0.22 * np.maximum(f["drug_era_count"] - 4, 0) - 0.09 * strain - 0.55 * f["condition_depression"]
    logit += -0.35 * f["lives_alone"] - 0.012 * f["copay_mean_eur"] + 0.45 * f["has_caregiver"]
    logit += 0.25 * (f["care_manager_contacts_12m"] > 0) - 0.3 * f["language_barrier"]
    f["pdc_180d"] = (1 / (1 + np.exp(-(logit + rng.normal(0, 0.6, rows))))).round(3)
    f["pdc_90d"] = np.clip(f["pdc_180d"] + rng.normal(0, 0.08, rows), 0, 1).round(3)
    f["adherent_80"] = f["pdc_180d"] >= 0.8
    f["inpatient_admissions_12m"] = rng.poisson(0.25 + 0.12 * f["charlson_index"] + 1.2 * (1 - f["pdc_180d"]), rows)
    f["emergency_visits_12m"] = rng.poisson(0.3 + 0.5 * f["inpatient_admissions_12m"], rows)
    f["visit_occurrence_count_12m"] = rng.poisson(4 + 1.5 * f["charlson_index"], rows)
    f["days_since_last_visit"] = rng.exponential(45, rows).round()
    f["missed_appointments_12m"] = rng.poisson(0.4 + 0.1 * strain + 0.8 * (1 - f["pdc_180d"]), rows)
    f["telehealth_visits_12m"] = rng.poisson(0.8, rows)
    f["portal_logins_90d"] = rng.poisson(2 + f["education_years"] / 8, rows)
    f["observation_period_days"] = rng.integers(365, 3650, rows)
    f["prior_readmission"] = f["inpatient_admissions_12m"] >= 2


def measurements(f: pd.DataFrame, rng: np.random.Generator) -> None:
    rows, diabetic = len(f), f["condition_type2_diabetes"]
    f["measurement_hba1c"] = np.where(diabetic, rng.normal(7.8, 1.3, rows), rng.normal(5.6, 0.4, rows)).round(1)
    f["measurement_systolic_bp"] = rng.normal(134 + 6 * f["condition_hypertension"], 15, rows).round()
    f["measurement_ldl"] = rng.normal(112, 32, rows).round()
    egfr = rng.normal(78 - 30 * f["condition_ckd"] - 0.4 * (f["age"] - 65), 15, rows)
    f["measurement_egfr"] = np.clip(egfr, 8, 130).round()
    f["measurement_bmi"] = rng.normal(27 + 7 * f["condition_obesity"], 4, rows).round(1)


def outcome(frame: pd.DataFrame, rng: np.random.Generator) -> pd.Series:
    """The 30-day readmission label, drawn from the causal equation on whatever feature values are present."""
    logit = -3.6 + 1.9 * (1 - frame["pdc_180d"]) + 0.32 * frame["charlson_index"]
    logit += 0.55 * (frame["inpatient_admissions_12m"] > 0) + 0.018 * (frame["age"] - 65)
    logit += 0.05 * frame["deprivation_index"] + 0.4 * frame["condition_heart_failure"] - 0.3 * frame["has_caregiver"]
    return pd.Series(rng.random(len(frame)) < 1 / (1 + np.exp(-logit)), index=frame.index, name=LABEL)


def seed_cohort(rows: int, rng: np.random.Generator) -> pd.DataFrame:
    """Draws the seed population from the causal structure, one feature per line in causal order."""
    frame = pd.DataFrame({"person_id": np.arange(1, rows + 1)})
    for stage in EXOGENOUS + ENDOGENOUS:
        stage(frame, rng)
    frame[LABEL] = outcome(frame, rng)
    return frame


def sampling_conditions(rows: int) -> list[Any]:
    """One sampling condition per combination of the categorical roots, sized by the product of their marginals."""
    from sdv.sampling import Condition

    combos = list(itertools.product(*[list(levels.items()) for levels in MARGINALS.values()]))
    counts = [int(rows * float(np.prod([share for _, share in combo]))) for combo in combos]
    counts[0] += rows - sum(counts)
    values = [dict(zip(MARGINALS, [level for level, _ in combo], strict=True)) for combo in combos]
    return [Condition(num_rows=n, column_values=v) for n, v in zip(counts, values, strict=True) if n > 0]


def synthesize(seed: pd.DataFrame, rows: int, epochs: int, rng: np.random.Generator) -> pd.DataFrame:
    """Fits CTGAN on the seed's root layer, samples it under the documented marginals, and computes the rest."""
    import torch
    from sdv.metadata import Metadata
    from sdv.single_table import CTGANSynthesizer

    torch.manual_seed(SEED)
    exogenous = seed.loc[:, [*MARGINALS, "age", "deprivation_index"]]
    metadata = Metadata.detect_from_dataframes({"patients": exogenous})
    synthesizer = CTGANSynthesizer(metadata, epochs=epochs, verbose=False)
    synthesizer.fit({"patients": exogenous})
    sampled = synthesizer.sample_from_conditions(sampling_conditions(rows), max_tries_per_batch=500)
    frame = sampled.reset_index(drop=True).astype(exogenous.dtypes.to_dict())
    frame.insert(0, "person_id", np.arange(1, len(frame) + 1))
    for stage in ENDOGENOUS:
        stage(frame, rng)
    frame[LABEL] = outcome(frame, rng)
    return pd.DataFrame(frame[seed.columns])


EXOGENOUS = [roots]
ENDOGENOUS = [household, conditions, drugs, adherence_and_contacts, measurements]


def role(column: str) -> str:
    return next((group for group, prefixes in ROLES.items() if column.startswith(prefixes)), "socioeconomic")


def schema(frame: pd.DataFrame) -> dict[str, Any]:
    columns = {str(name): {"dtype": str(dtype), "role": role(str(name))} for name, dtype in frame.dtypes.items()}
    return {"label": LABEL, "features": len(columns) - 2, "columns": columns}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=ROWS)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args()
    generator = np.random.default_rng(SEED)
    cohort = synthesize(seed_cohort(SEED_ROWS, generator), args.rows, args.epochs, generator)
    DATA.mkdir(exist_ok=True)
    cohort.to_parquet(DATA / "cohort.parquet", index=False)
    (DATA / "schema.json").write_text(json.dumps(schema(cohort), indent=1), encoding="utf-8")
    rate, pdc = cohort[LABEL].mean(), cohort["pdc_180d"].mean()
    print(f"{len(cohort)} patients, {len(cohort.columns) - 2} features, readmission {rate:.3f}, mean PDC {pdc:.3f}")
