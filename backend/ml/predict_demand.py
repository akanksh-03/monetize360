import os
import joblib

ML_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(ML_DIR, "demand_model.pkl")

_model = None


def _load_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError("No trained model found — run train_demand_model.py first.")
        _model = joblib.load(MODEL_PATH)
    return _model


def predict_demand(context: dict) -> float:
    model = _load_model()
    inventory_pct = context.get("inventory_pct", 0.5)
    base_price = context.get("base_price")
    mrp = context.get("mrp")
    if base_price is None or mrp is None or mrp == 0:
        discount_ratio = 0.2
    else:
        discount_ratio = 1 - (base_price / mrp)
    is_loyalty = 1 if context.get("customer_segment") == "loyalty" else 0
    pred = model.predict([[inventory_pct, discount_ratio, is_loyalty]])[0]
    return max(0.0, min(1.0, float(pred)))