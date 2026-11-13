
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


BASE_DIR = Path(__file__).resolve().parents[2]

DATA_PATH = BASE_DIR / "data" / "processed" / "eta_features.csv"
MODEL_DIR = BASE_DIR / "models"
REPORT_PATH = BASE_DIR / "data" / "processed" / "model_evaluation.json"
SPLIT_REPORT_PATH = BASE_DIR / "data" / "processed" / "model_split_summary.json"

SEED = 20261022
TEST_FRACTION = 0.20


REQUIRED_COLUMNS = [
    "shipment_id",
    "prediction_time",
    "feature_cutoff_time",
    "actual_delivered_at",
    "target_remaining_minutes",
    "target_delay_minutes",
    "target_is_delayed",
]

EXCLUDED_FEATURES = [
    "shipment_id",
    "prediction_time",
    "feature_cutoff_time",
    "actual_delivered_at",
    "target_remaining_minutes",
    "target_delay_minutes",
    "target_is_delayed",
]


def build_preprocessor(X):
    categorical_columns = X.select_dtypes(
        include=["object", "category"]
    ).columns.tolist()

    numeric_columns = X.select_dtypes(
        include=["number", "bool"]
    ).columns.tolist()

    if not numeric_columns and not categorical_columns:
        raise ValueError("No usable model features found.")

    transformers = []

    if numeric_columns:
        numeric_transformer = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
        ])

        transformers.append(
            ("numeric", numeric_transformer, numeric_columns)
        )

    if categorical_columns:
        categorical_transformer = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore")),
        ])

        transformers.append(
            ("categorical", categorical_transformer, categorical_columns)
        )

    preprocessor = ColumnTransformer(transformers)

    return preprocessor, numeric_columns, categorical_columns


def validate_dataset(df):
    missing = [
        column for column in REQUIRED_COLUMNS
        if column not in df.columns
    ]

    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    if df.empty:
        raise ValueError("Feature dataset is empty.")

    timestamp_columns = [
        "prediction_time",
        "feature_cutoff_time",
        "actual_delivered_at",
    ]

    for column in timestamp_columns:
        df[column] = pd.to_datetime(
            df[column],
            errors="coerce"
        )

    numeric_columns = [
        "target_remaining_minutes",
        "target_delay_minutes",
        "target_is_delayed",
    ]

    for column in numeric_columns:
        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )

    df = df.dropna(subset=REQUIRED_COLUMNS).copy()

    if df.empty:
        raise ValueError("No valid rows remain after cleaning.")

    if (df["target_remaining_minutes"] <= 0).any():
        raise ValueError(
            "Found non-positive remaining-time targets."
        )

    if (df["feature_cutoff_time"] > df["prediction_time"]).any():
        raise ValueError(
            "Temporal leakage: feature cutoff is after prediction time."
        )

    if (df["prediction_time"] >= df["actual_delivered_at"]).any():
        raise ValueError(
            "Invalid snapshot: prediction time is at/after delivery."
        )

    if not set(df["target_is_delayed"].unique()).issubset({0, 1}):
        raise ValueError("Delay labels must be binary: 0 or 1.")

    if df["shipment_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Empty shipment IDs found.")

    df["target_is_delayed"] = df["target_is_delayed"].astype(int)

    return df


def create_temporal_split(df):
    shipment_order = (
        df.groupby("shipment_id")["prediction_time"]
        .min()
        .sort_values()
    )

    shipment_ids = shipment_order.index.tolist()

    if len(shipment_ids) < 5:
        raise ValueError(
            "At least five distinct shipments are required."
        )

    split_index = int(
        len(shipment_ids) * (1 - TEST_FRACTION)
    )

    split_index = max(
        1,
        min(split_index, len(shipment_ids) - 1)
    )

    train_shipments = set(shipment_ids[:split_index])
    test_shipments = set(shipment_ids[split_index:])

    test_start_time = shipment_order.iloc[split_index]

    train_df = df[
        df["shipment_id"].isin(train_shipments)
        & (df["prediction_time"] < test_start_time)
    ].copy()

    test_df = df[
        df["shipment_id"].isin(test_shipments)
    ].copy()

    if train_df.empty or test_df.empty:
        raise ValueError(
            "Temporal split produced an empty training or test set."
        )

    if set(train_df["shipment_id"]) & set(test_df["shipment_id"]):
        raise ValueError(
            "Shipment leakage detected between training and testing."
        )

    if train_df["prediction_time"].max() >= test_df["prediction_time"].min():
        raise ValueError(
            "Temporal ordering violation between training and testing."
        )

    return (
        train_df,
        test_df,
        train_shipments,
        test_shipments,
        test_start_time,
    )


def train_models():
    print("Loading ETA feature dataset...")

    if not DATA_PATH.exists():
        raise FileNotFoundError(
            f"Feature dataset not found: {DATA_PATH}"
        )

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(DATA_PATH)

    df = validate_dataset(df)

    (
        train_df,
        test_df,
        train_shipments,
        test_shipments,
        test_start_time,
    ) = create_temporal_split(df)

    y_reg_train = train_df["target_remaining_minutes"]
    y_reg_test = test_df["target_remaining_minutes"]

    y_cls_train = train_df["target_is_delayed"]
    y_cls_test = test_df["target_is_delayed"]

    if y_cls_train.nunique() != 2:
        raise ValueError(
            "Training set must contain both on-time and delayed shipments."
        )

    if y_cls_test.nunique() != 2:
        raise ValueError(
            "Test set must contain both on-time and delayed shipments. "
            "A larger dataset or different time window may be required."
        )

    X_train = train_df.drop(
        columns=EXCLUDED_FEATURES,
        errors="ignore"
    )

    X_test = test_df.drop(
        columns=EXCLUDED_FEATURES,
        errors="ignore"
    )

    if list(X_train.columns) != list(X_test.columns):
        raise ValueError("Training and testing feature columns do not match.")

    preprocessor_reg, numeric_columns, categorical_columns = (
        build_preprocessor(X_train)
    )

    preprocessor_cls, _, _ = build_preprocessor(X_train)

    print("\nDATASET SUMMARY")
    print("----------------")
    print("Total rows:", len(df))
    print("Training rows:", len(train_df))
    print("Testing rows:", len(test_df))
    print("Training shipments:", len(train_shipments))
    print("Testing shipments:", len(test_shipments))
    print("Numeric features:", len(numeric_columns))
    print("Categorical features:", len(categorical_columns))
    print("Test period starts:", test_start_time)

    split_summary = {
        "split_method": "chronological shipment-level split",
        "random_seed": SEED,
        "test_fraction": TEST_FRACTION,
        "total_rows": int(len(df)),
        "training_rows": int(len(train_df)),
        "testing_rows": int(len(test_df)),
        "training_shipments": int(len(train_shipments)),
        "testing_shipments": int(len(test_shipments)),
        "training_period_start": str(train_df["prediction_time"].min()),
        "training_period_end": str(train_df["prediction_time"].max()),
        "testing_period_start": str(test_df["prediction_time"].min()),
        "testing_period_end": str(test_df["prediction_time"].max()),
        "shipment_overlap": 0,
    }

    with open(SPLIT_REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(split_summary, file, indent=4)

    # ETA REGRESSION

    print("\nTraining ETA regression model...")

    eta_model = Pipeline([
        ("preprocessor", preprocessor_reg),
        (
            "model",
            RandomForestRegressor(
                n_estimators=300,
                random_state=SEED,
                n_jobs=-1,
                min_samples_leaf=2,
            ),
        ),
    ])

    eta_model.fit(X_train, y_reg_train)

    remaining_predictions = eta_model.predict(X_test)
    remaining_predictions = np.maximum(
        remaining_predictions,
        0
    )

    remaining_mae = mean_absolute_error(
        y_reg_test,
        remaining_predictions
    )

    remaining_rmse = np.sqrt(
        mean_squared_error(
            y_reg_test,
            remaining_predictions
        )
    )

    predicted_arrivals = (
        test_df["prediction_time"]
        + pd.to_timedelta(
            remaining_predictions,
            unit="m"
        )
    )

    actual_arrivals = test_df["actual_delivered_at"]

    eta_timestamp_errors = (
        predicted_arrivals - actual_arrivals
    ).dt.total_seconds().abs() / 60

    eta_timestamp_mae = float(
        eta_timestamp_errors.mean()
    )

    # DELAY CLASSIFICATION

    print("\nTraining delay classification model...")

    delay_model = Pipeline([
        ("preprocessor", preprocessor_cls),
        (
            "model",
            RandomForestClassifier(
                n_estimators=300,
                random_state=SEED,
                n_jobs=-1,
                min_samples_leaf=2,
                class_weight="balanced",
            ),
        ),
    ])

    delay_model.fit(X_train, y_cls_train)

    delay_predictions = delay_model.predict(X_test)

    delay_probabilities = delay_model.predict_proba(X_test)[:, 1]

    accuracy = accuracy_score(
        y_cls_test,
        delay_predictions
    )

    precision = precision_score(
        y_cls_test,
        delay_predictions,
        zero_division=0
    )

    recall = recall_score(
        y_cls_test,
        delay_predictions,
        zero_division=0
    )

    f1 = f1_score(
        y_cls_test,
        delay_predictions,
        zero_division=0
    )

    roc_auc = roc_auc_score(
        y_cls_test,
        delay_probabilities
    )

    matrix = confusion_matrix(
        y_cls_test,
        delay_predictions,
        labels=[0, 1]
    )

    tn, fp, fn, tp = matrix.ravel()

    results = {
        "dataset": {
            "total_rows": int(len(df)),
            "training_rows": int(len(train_df)),
            "testing_rows": int(len(test_df)),
            "training_shipments": int(len(train_shipments)),
            "testing_shipments": int(len(test_shipments)),
            "feature_count": int(len(X_train.columns)),
            "numeric_feature_count": len(numeric_columns),
            "categorical_feature_count": len(categorical_columns),
        },
        "validation": {
            "split_method": "chronological shipment-level split",
            "random_seed": SEED,
            "test_fraction": TEST_FRACTION,
            "test_period_start": str(test_start_time),
            "shipment_overlap": 0,
            "future_feature_cutoff_rows": 0,
        },
        "eta_regression": {
            "target": "remaining_minutes_until_actual_delivery",
            "remaining_time_MAE_minutes": round(
                float(remaining_mae), 4
            ),
            "remaining_time_RMSE_minutes": round(
                float(remaining_rmse), 4
            ),
            "predicted_arrival_timestamp_MAE_minutes": round(
                eta_timestamp_mae, 4
            ),
        },
        "delay_classification": {
            "target": "actual_delivery_after_sla_deadline",
            "accuracy": round(float(accuracy), 4),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "f1_score": round(float(f1), 4),
            "roc_auc": round(float(roc_auc), 4),
            "confusion_matrix": {
                "true_negative": int(tn),
                "false_positive": int(fp),
                "false_negative": int(fn),
                "true_positive": int(tp),
            },
        },
    }

    joblib.dump(
        eta_model,
        MODEL_DIR / "eta_regression_model.joblib"
    )

    joblib.dump(
        delay_model,
        MODEL_DIR / "delay_classification_model.joblib"
    )

    with open(REPORT_PATH, "w", encoding="utf-8") as file:
        json.dump(results, file, indent=4)

    print("\nMODEL TRAINING COMPLETED")
    print("------------------------")

    print("\nETA REGRESSION")
    print("Remaining-time MAE:", round(remaining_mae, 4), "minutes")
    print("Remaining-time RMSE:", round(remaining_rmse, 4), "minutes")
    print("Arrival timestamp MAE:", round(eta_timestamp_mae, 4), "minutes")

    print("\nDELAY CLASSIFICATION")
    print("Accuracy:", round(accuracy, 4))
    print("Precision:", round(precision, 4))
    print("Recall:", round(recall, 4))
    print("F1 Score:", round(f1, 4))
    print("ROC-AUC:", round(roc_auc, 4))

    print("\nCONFUSION MATRIX")
    print("True Negatives:", tn)
    print("False Positives:", fp)
    print("False Negatives:", fn)
    print("True Positives:", tp)

    print("\nSaved files:")
    print("models/eta_regression_model.joblib")
    print("models/delay_classification_model.joblib")
    print("data/processed/model_evaluation.json")
    print("data/processed/model_split_summary.json")


if __name__ == "__main__":
    train_models()
