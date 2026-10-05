import os
import numpy as np
import joblib

ML_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ML_DIR, "anomaly_model.pkl")

_model = None


def _load_model():
    global _model

    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                "No anomaly model found — run train_anomaly_model.py first."
            )

        _model = joblib.load(MODEL_PATH)

    return _model


def detect_anomaly(context: dict) -> dict:
    """Detect unusual ecommerce pricing scenarios."""

    model = _load_model()

    inventory_pct = context.get("inventory_pct", 0.5)
    base_price = context.get("base_price")
    mrp = context.get("mrp")
    demand_score = context.get("demand_score", 0.5)

    discount_ratio = (
        1 - (base_price / mrp)
        if base_price is not None and mrp is not None and mrp != 0
        else 0.2
    )

    x = np.array([
        inventory_pct,
        discount_ratio,
        demand_score
    ])

    diff = x - model["mean"]

    distance = float(
        np.sqrt(diff @ model["cov_inv"] @ diff)
    )

    is_anomaly = bool(distance > model["threshold"])

    return {
        "is_anomaly": is_anomaly,
        "distance": round(distance, 3),
        "threshold": round(float(model["threshold"]), 3),
    }