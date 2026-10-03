import os
import json

import joblib
from sklearn.linear_model import LinearRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

ML_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(ML_DIR)
DATA_PATH = os.path.join(BACKEND_DIR, "data", "transactions", "synthetic_transactions.json")
MODEL_PATH = os.path.join(ML_DIR, "demand_model.pkl")


def build_features(row):
    discount_ratio = 1 - (row["base_price"] / row["mrp"])
    return [row["inventory_pct"], discount_ratio]


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)

    rows = data["ecommerce"]
    X = [build_features(r) for r in rows]
    y = [r["demand_score"] for r in rows]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = LinearRegression()
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    print(f"Trained on {len(X_train)} rows, tested on {len(X_test)} rows")
    print(f"MAE: {mae:.4f}")
    print(f"R2:  {r2:.4f}")
    print(f"Coefficients: inventory_pct={model.coef_[0]:.4f}, discount_ratio={model.coef_[1]:.4f}")

    joblib.dump(model, MODEL_PATH)
    print(f"Model saved to {MODEL_PATH}")


if __name__ == "__main__":
    main()