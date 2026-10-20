"""Trains the readmission-risk model as one scikit-learn pipeline whose preprocessing travels with it.

The model is a `Pipeline`: a `ColumnTransformer` that imputes and one-hot-encodes the nominal
columns and imputes the numeric ones, then a gradient-boosting classifier (the baseline; ADR-009
rejects deep learning at this size) or a logistic regression (experiment 001). Every
hyperparameter is a command-line option, so this component is also the trial of the sweep, and
the validation metrics it logs, the business metric among them, carry the names the sweep
optimises. The fitted pipeline is written as an MLflow model, the format every endpoint consumes.
"""

import argparse
from pathlib import Path
from typing import Any

import mlflow
import pandas as pd
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.components.prep import IDENTIFIER, NOMINAL, contract
from src.economics import Economics, arguments, summary

FAMILIES = ("gradient_boosting", "logistic_regression")
DEFAULTS: dict[str, Any] = {"learning_rate": 0.05, "max_iter": 300, "max_leaf_nodes": 31}
DEFAULTS |= {"min_samples_leaf": 20, "l2_regularization": 0.0}


def features_of(frame: pd.DataFrame, label: str) -> list[str]:
    return [name for name in frame.columns if name not in (label, IDENTIFIER)]


def classifier(family: str, params: dict[str, Any], seed: int) -> Any:
    if family == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    return HistGradientBoostingClassifier(random_state=seed, **params)


def model(features: list[str], family: str, params: dict[str, Any], seed: int) -> Pipeline:
    """Preprocessing and classifier in one object, so serving and explanation see the raw columns."""
    nominal = [name for name in features if name in NOMINAL]
    numeric = [name for name in features if name not in NOMINAL]
    encode = make_pipeline(SimpleImputer(strategy="most_frequent"), OneHotEncoder(handle_unknown="ignore"))
    preprocess = ColumnTransformer(
        [("nominal", encode, nominal), ("numeric", SimpleImputer(strategy="median"), numeric)]
    )
    return Pipeline([("preprocess", preprocess), ("classifier", classifier(family, params, seed))])


def fit(
    train: pd.DataFrame, validation: pd.DataFrame, family: str, params: dict[str, Any], seed: int, economics: Economics
) -> tuple[Pipeline, dict[str, float]]:
    """Fits on the training split and prices the ranking on the validation split."""
    label = contract()["label"]
    features = features_of(train, label)
    pipeline = model(features, family, params, seed).fit(train[features], train[label])
    scores = pipeline.predict_proba(validation[features])[:, 1]
    outcomes = validation[label].to_numpy()
    metrics = {"auc": roc_auc_score(outcomes, scores), "average_precision": average_precision_score(outcomes, scores)}
    metrics |= summary(outcomes, scores, economics)
    return pipeline, {f"validation_{name}": float(value) for name, value in metrics.items()}


def main(args: argparse.Namespace) -> dict[str, float]:
    """One explicit run; autolog would otherwise open and close its own, and the validation metrics would go astray."""
    mlflow.sklearn.autolog(log_models=False, silent=True)
    train, validation = pd.read_parquet(args.train), pd.read_parquet(args.validation)
    params = {name: getattr(args, name) for name in DEFAULTS}
    with mlflow.start_run():
        pipeline, metrics = fit(train, validation, args.family, params, args.seed, Economics.from_args(args))
        mlflow.log_params({"family": args.family, "seed": args.seed} | (params if args.family == FAMILIES[0] else {}))
        mlflow.log_metrics(metrics)
        example = train[features_of(train, contract()["label"])].head(5)
        signature = infer_signature(example, pipeline.predict_proba(example)[:, 1])
        mlflow.sklearn.save_model(pipeline, str(args.model), signature=signature, input_example=example)
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--family", choices=FAMILIES, default=FAMILIES[0])
    parser.add_argument("--seed", type=int, default=7)
    for name, default in DEFAULTS.items():
        parser.add_argument(f"--{name.replace('_', '-')}", type=type(default), default=default)
    arguments(parser)
    print(main(parser.parse_args()))
