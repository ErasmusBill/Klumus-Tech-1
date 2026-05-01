import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split

from ai_predictor.feature_engineering import FEATURE_COLUMNS


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "training_data.csv"
MODEL_PATH = Path(__file__).resolve().parent / "performance_model.pkl"
MODEL_META_PATH = Path(__file__).resolve().parent / "performance_model_meta.json"


def train_model():
    if not DATA_PATH.exists():
        raise FileNotFoundError(f"Training data not found: {DATA_PATH}")

    df = pd.read_csv(DATA_PATH)
    if "final_grade" not in df.columns:
        raise ValueError("The dataset must contain a 'final_grade' column.")

    missing_features = [name for name in FEATURE_COLUMNS if name not in df.columns]
    if missing_features:
        raise ValueError(f"Missing feature columns: {', '.join(missing_features)}")

    allowed_grades = {"A", "B", "C", "D", "F"}
    df["final_grade"] = df["final_grade"].astype(str).str.strip().str.upper()
    df = df.dropna(subset=[*FEATURE_COLUMNS, "final_grade"])
    df = df[df["final_grade"].isin(allowed_grades)]

    if df.empty:
        raise ValueError("No valid rows available for training after preprocessing.")

    X = df[list(FEATURE_COLUMNS)]
    y = df["final_grade"]

    # Small datasets are common early on; avoid brittle splits.
    can_split = len(df) >= 4
    if can_split:
        stratify = y if y.nunique() > 1 and y.value_counts().min() > 1 else None
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.25, random_state=42, stratify=stratify
        )
    else:
        X_train, y_train = X, y
        X_test = y_test = None

    model = RandomForestClassifier(n_estimators=200, random_state=42)
    model.fit(X_train, y_train)

    if X_test is not None and len(X_test) > 0:
        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        print(f"Model trained successfully. Accuracy: {acc * 100:.2f}%")
    else:
        print("Model trained successfully. Dataset too small for holdout accuracy.")

    joblib.dump(model, MODEL_PATH)

    metadata = {
        "feature_columns": list(FEATURE_COLUMNS),
        "trained_rows": int(len(df)),
        "classes": sorted(y.unique().tolist()),
    }
    MODEL_META_PATH.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Model saved to {MODEL_PATH}")
    print(f"Model metadata saved to {MODEL_META_PATH}")
