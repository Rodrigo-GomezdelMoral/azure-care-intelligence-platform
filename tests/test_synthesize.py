import numpy as np

from src.data.synthesize import LABEL, outcome, schema, seed_cohort


def test_seed_cohort_has_the_documented_shape_and_no_identifier_beyond_person_id() -> None:
    frame = seed_cohort(3000, np.random.default_rng(1))
    described = schema(frame)
    assert described["features"] == 57 and described["label"] == LABEL and frame["person_id"].is_unique
    assert set(frame.columns) == set(described["columns"]) and frame.isna().sum().sum() == 0
    roles = {column["role"] for column in described["columns"].values()}
    assert roles == {
        "person",
        "demographic",
        "socioeconomic",
        "comorbidity",
        "prescription",
        "contact",
        "measurement",
        "outcome",
    }
    assert all(dtype.kind in "biuf" for dtype in frame.dtypes), "every column is numeric or boolean; nothing free-text"


def test_the_causal_structure_puts_real_signal_in_the_label() -> None:
    frame = seed_cohort(20000, np.random.default_rng(2))
    rate = frame[LABEL].mean()
    assert 0.10 < rate < 0.30
    low, high = frame[frame["pdc_180d"] < 0.5][LABEL].mean(), frame[frame["pdc_180d"] > 0.8][LABEL].mean()
    assert low > 2 * high, "non-adherent patients are readmitted far more often"
    by_charlson = frame.groupby(frame["charlson_index"].clip(upper=4))[LABEL].mean()
    assert by_charlson.is_monotonic_increasing
    polypharmacy, simple = (
        frame[frame["drug_era_count"] >= 6]["pdc_180d"].mean(),
        frame[frame["drug_era_count"] <= 3]["pdc_180d"].mean(),
    )
    assert polypharmacy < simple - 0.05, "polypharmacy lowers adherence"


def test_the_outcome_is_reproducible_from_a_seed() -> None:
    frame = seed_cohort(500, np.random.default_rng(3))
    first, second = outcome(frame, np.random.default_rng(9)), outcome(frame, np.random.default_rng(9))
    assert first.equals(second) and first.dtype == bool
