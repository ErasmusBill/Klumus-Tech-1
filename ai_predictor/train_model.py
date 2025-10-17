import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import joblib
import os

def train_model():
    df = pd.read_csv("training_data.csv")

   
    grade_map = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
    if "final_grade" not in df.columns:
        raise ValueError("❌ The dataset must contain a 'final_grade' column.")
    
    df["final_grade"] = df["final_grade"].map(grade_map)


    df = df.dropna(subset=["attendance", "average_score", "discipline", "homework", "final_grade"])


    X = df[["attendance", "average_score", "discipline", "homework"]]
    y = df["final_grade"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)


    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)
    print(f"✅ Model trained successfully! Accuracy: {acc*100:.2f}%")


    os.makedirs("ai_predictor", exist_ok=True)
    joblib.dump(model, "ai_predictor/performance_model.pkl")
    print("📦 Model saved as ai_predictor/performance_model.pkl")

