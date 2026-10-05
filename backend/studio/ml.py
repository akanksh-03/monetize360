"""Portable NumPy model demo. No sklearn imports; no fabricated real-data claims."""
from functools import lru_cache
import importlib
import json
import os
import numpy as np
from .storage import ROOT
from .validation import StudioError, number

FEATURES = ["traffic_index", "promotion", "competitor_price_ratio", "hour_sin"]


@lru_cache(maxsize=1)
def artifact():
    path = ROOT / "backend/studio/assets/demo_model.json"
    if not path.exists():
        raise StudioError("Train the portable model: python scripts/train_studio_model.py", "MODEL_UNAVAILABLE", 503)
    return json.loads(path.read_text(encoding="utf-8"))


def design(x, kind):
    if kind == "PolynomialRidge":
        parts = [x, x*x]
        parts.extend((x[:, i]*x[:, j])[:, None] for i in range(x.shape[1]) for j in range(i+1, x.shape[1]))
        return np.concatenate(parts, axis=1)
    return x


def fit(x, y, kind, seed=42):
    mean, scale = x.mean(axis=0), x.std(axis=0)+1e-8
    z = (x-mean)/scale
    if kind == "MLP":
        rng = np.random.default_rng(seed)
        w1, b1 = rng.normal(0, .2, (x.shape[1], 8)), np.zeros(8)
        w2, b2 = rng.normal(0, .15, 8), float(y.mean())
        for _ in range(450):
            h = np.tanh(z @ w1 + b1)
            error = 2*(h @ w2 + b2-y)/len(y)
            hidden_grad = error[:, None]*w2[None, :]*(1-h*h)
            dw2, db2 = h.T @ error + .002*w2, error.sum()
            dw1, db1 = z.T @ hidden_grad + .002*w1, hidden_grad.sum(axis=0)
            w1 -= .025*dw1; b1 -= .025*db1
            w2 -= .025*dw2; b2 -= .025*db2
        params = {"w1": w1.tolist(), "b1": b1.tolist(), "w2": w2.tolist(), "b2": b2}
    else:
        f = design(z, kind)
        f = np.column_stack([np.ones(len(f)), f])
        penalty = np.eye(f.shape[1]) * (.5 if kind == "PolynomialRidge" else 0)
        penalty[0, 0] = 0
        coeff = np.linalg.pinv(f.T @ f + penalty) @ f.T @ y
        params = {"coefficients": coeff.tolist()}
    return {"kind": kind, "mean": mean.tolist(), "scale": scale.tolist(), **params}


def predict_array(model, x):
    z = (x-np.array(model["mean"]))/np.array(model["scale"])
    if model["kind"] == "MLP":
        result = np.tanh(z @ np.array(model["w1"])+np.array(model["b1"])) @ np.array(model["w2"]) + model["b2"]
    else:
        f = np.column_stack([np.ones(len(z)), design(z, model["kind"])])
        result = f @ np.array(model["coefficients"])
    return np.clip(result, 0, 1)


def external_adapter():
    value = os.environ.get("MONETIZE_DEMAND_ADAPTER", "")
    if not value:
        return None
    try:
        module, attr = value.split(":", 1)
        return getattr(importlib.import_module(module), attr)
    except (ValueError, ImportError, AttributeError) as e:
        raise StudioError("The configured demand adapter could not be loaded.", "MODEL_UNAVAILABLE", 503) from e


def report():
    if os.environ.get("MONETIZE_DEMAND_ADAPTER"):
        return {"source": "external_adapter", "note": "Your existing model is connected through an adapter. Its metrics are not replaced by the portable demo metrics."}
    a = artifact()
    return {k: v for k, v in a.items() if k not in ("model", "covariance_inverse", "feature_center")}


def predict(context):
    adapter = external_adapter()
    if adapter:
        result = adapter(dict(context))
        if not isinstance(result, dict) or not result.get("model_version"):
            raise StudioError("Demand adapter must return demand_score and model_version.")
        score = number(result.get("demand_score"), "predicted demand_score")
        if not 0 <= score <= 1:
            raise StudioError("Predicted demand_score must be between 0 and 1.")
        return {**result, "source": "external_adapter"}
    required = ["traffic_index", "promotion", "competitor_price_ratio", "hour"]
    for key in required:
        if key not in context:
            raise StudioError(f"Portable demand prediction requires {key}.")
    traffic = number(context["traffic_index"], "traffic_index")
    competitor = number(context["competitor_price_ratio"], "competitor_price_ratio")
    hour = number(context["hour"], "hour")
    if not isinstance(context["promotion"], bool) or not 0 <= hour <= 23 or not 0 <= traffic <= 1 or competitor <= 0:
        raise StudioError("Check traffic (0–1), hour (0–23), promotion (boolean), and competitor ratio (>0).")
    x = np.array([[traffic, float(context["promotion"]), competitor, np.sin(2*np.pi*hour/24)]])
    a = artifact()
    score = float(predict_array(a["model"], x)[0])
    diff = x[0]-np.array(a["feature_center"])
    distance = float(diff @ np.array(a["covariance_inverse"]) @ diff)
    return {"demand_score": score, "model_version": a["model_version"], "selected_model": a["selected_model"],
            "source": a["source"], "anomaly_score": distance, "anomaly_threshold": a["anomaly_threshold"],
            "anomaly": distance > a["anomaly_threshold"],
            "note": "Synthetic-data demonstration; this does not establish real-world forecasting accuracy."}
