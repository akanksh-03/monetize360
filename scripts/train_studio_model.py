"""Reproducible portable demonstration: 5-fold selection + untouched test set.

Only NumPy is used. Labels are synthetic and clearly identified in the UI.
This is a separate artifact; it does not replace backend/ml or its saved models.
"""
from pathlib import Path
import hashlib
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.studio.ml import fit, predict_array, FEATURES


def main():
    rng = np.random.default_rng(20261005)
    n = 1400
    traffic = rng.uniform(0, 1, n)
    promotion = rng.binomial(1, .30, n)
    competitor = rng.uniform(.8, 1.2, n)
    hours = rng.integers(0, 24, n)
    x = np.column_stack([traffic, promotion, competitor, np.sin(2*np.pi*hours/24)])
    # Known noisy linear data-generating process: no claim of real sales training.
    y = np.clip(.17 + .51*traffic + .11*promotion - .13*(competitor-1)
                + .04*x[:, 3] + rng.normal(0, .045, n), 0, 1)
    order = rng.permutation(n)
    train, calibration, test = order[:980], order[980:1190], order[1190:]
    folds = np.array_split(train, 5)
    records = []
    for kind in ["LinearRegression", "PolynomialRidge", "MLP"]:
        mae, rmse = [], []
        for i in range(5):
            fitting = np.concatenate([folds[j] for j in range(5) if j != i])
            validation = folds[i]
            model = fit(x[fitting], y[fitting], kind, seed=42+i)
            delta = predict_array(model, x[validation])-y[validation]
            mae.append(float(np.abs(delta).mean()))
            rmse.append(float(np.sqrt(np.mean(delta**2))))
        records.append({"model": kind, "cv_mae_mean": float(np.mean(mae)),
                        "cv_mae_std": float(np.std(mae, ddof=1)),
                        "cv_rmse_mean": float(np.mean(rmse)), "fold_mae": mae})
    winner = min(records, key=lambda r: r["cv_mae_mean"])["model"]
    model = fit(x[train], y[train], winner)
    pred = predict_array(model, x[test])
    error = pred-y[test]
    center = x[train].mean(axis=0)
    covariance = np.cov(x[train], rowvar=False)
    inverse = np.linalg.pinv(covariance + np.eye(x.shape[1])*1e-5)
    caldiff = x[calibration]-center
    distances = np.einsum("ij,jk,ik->i", caldiff, inverse, caldiff)
    threshold = float(np.quantile(distances, .99))
    model_version = hashlib.sha256(json.dumps(model, sort_keys=True).encode()).hexdigest()[:16]
    output = {"source": "synthetic_demo", "model_version": model_version, "selected_model": winner,
              "target": "Synthetic demand index (0–1); not observed sales or real market demand",
              "features": FEATURES, "random_seed": 20261005,
              "split": {"training": len(train), "anomaly_calibration": len(calibration), "test": len(test)},
              "selection": "5-fold CV on training only; preprocessing fitted inside each fold",
              "candidates": records,
              "test_metrics": {"mae": float(np.abs(error).mean()), "rmse": float(np.sqrt(np.mean(error**2))),
                               "r2": float(1-np.sum(error**2)/np.sum((y[test]-y[test].mean())**2)),
                               "mean_baseline_mae": float(np.abs(y[test]-y[train].mean()).mean())},
              "anomaly_threshold": threshold, "anomaly_threshold_method": "99th percentile of held-out nominal calibration distances",
              "anomaly_limit": "Out-of-distribution heuristic, not a calibrated probability of incorrect pricing",
              "model": model, "feature_center": center.tolist(), "covariance_inverse": inverse.tolist(),
              "limitations": "All reported metrics describe the seeded synthetic dataset only. Use an external adapter for your existing model."}
    path = ROOT / "backend/studio/assets/demo_model.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, indent=2, allow_nan=False), encoding="utf-8")
    print(f"Selected {winner}; held-out MAE {output['test_metrics']['mae']:.4f}. Synthetic data only.")
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
