import os
import json
import numpy as np
import joblib

ML_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(ML_DIR)
DATA_PATH = os.path.join(BACKEND_DIR, "data", "transactions", "synthetic_transactions.json")
MODEL_PATH = os.path.join(ML_DIR, "anomaly_model.pkl")

FEATURE_NAMES = ["inventory_pct", "discount_ratio", "demand_score"]


def build_features(row):
    discount_ratio = 1 - (row["base_price"] / row["mrp"])
    return [row["inventory_pct"], discount_ratio, row["demand_score"]]


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)
    rows = data["ecommerce"]
    X = np.array([build_features(r) for r in rows])

    mean = X.mean(axis=0)
    cov = np.cov(X, rowvar=False)
    cov_inv = np.linalg.pinv(cov)

    diffs = X - mean
    distances = np.sqrt(np.einsum('ij,jk,ik->i', diffs, cov_inv, diffs))
    threshold = np.percentile(distances, 97.5)

    model = {"mean": mean, "cov_inv": cov_inv, "threshold": threshold, "feature_names": FEATURE_NAMES}
    joblib.dump(model, MODEL_PATH)

    n_flagged = int((distances > threshold).sum())
    print(f"Trained on {len(X)} rows")
    print(f"Mahalanobis distance threshold (97.5th percentile): {threshold:.3f}")
    print(f"Rows flagged as anomalous at this threshold: {n_flagged} ({n_flagged/len(X)*100:.1f}%)")
    print(f"Saved anomaly model to {MODEL_PATH}")


if __name__ == "__main__":
    main()