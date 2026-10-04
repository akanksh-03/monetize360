import os
import json

import joblib
import numpy as np
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, cross_val_score, KFold
from sklearn.metrics import mean_absolute_error, r2_score

ML_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(ML_DIR)
DATA_PATH = os.path.join(BACKEND_DIR, "data", "transactions", "synthetic_transactions.json")
MODEL_PATH = os.path.join(ML_DIR, "demand_model.pkl")
META_PATH = os.path.join(ML_DIR, "demand_model_meta.json")

FEATURE_NAMES = ["inventory_pct", "discount_ratio", "is_loyalty"]


def build_features(row):
    discount_ratio = 1 - (row["base_price"] / row["mrp"])
    is_loyalty = 1 if row["customer_segment"] == "loyalty" else 0
    return [row["inventory_pct"], discount_ratio, is_loyalty]


def main():
    with open(DATA_PATH) as f:
        data = json.load(f)
    rows = data["ecommerce"]

    X = np.array([build_features(r) for r in rows])
    y = np.array([r["demand_score"] for r in rows])

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    candidates = {
        "LinearRegression": LinearRegression(),
        "PolynomialRidge": Pipeline([
            ("poly", PolynomialFeatures(degree=2, include_bias=False)),
            ("ridge", Ridge(alpha=1.0)),
        ]),
        "NeuralNet": Pipeline([
            ("scale", StandardScaler()),
            ("mlp", MLPRegressor(hidden_layer_sizes=(16, 8), activation="relu",
                                  max_iter=3000, early_stopping=True,
                                  random_state=42)),
        ]),
    }

    kfold = KFold(n_splits=5, shuffle=True, random_state=42)
    results = {}

    print(f"{'Model':<18} {'CV R2 (mean±std)':<22} {'Test MAE':<10} {'Test R2':<10}")
    print("-" * 62)

    for name, model in candidates.items():
        cv_scores = cross_val_score(model, X_train, y_train, cv=kfold, scoring="r2")
        model.fit(X_train, y_train)
        preds = model.predict(X_test)
        mae = mean_absolute_error(y_test, preds)
        r2 = r2_score(y_test, preds)
        results[name] = {"model": model, "cv_r2_mean": cv_scores.mean(), "cv_r2_std": cv_scores.std(), "test_mae": mae, "test_r2": r2}
        print(f"{name:<18} {cv_scores.mean():.3f} \u00b1 {cv_scores.std():.3f}      {mae:.4f}     {r2:.4f}")

    best_name = max(results, key=lambda n: results[n]["cv_r2_mean"])
    best = results[best_name]
    best_model = best["model"]

    print(f"\nBest model (by cross-validated R2): {best_name}")
    print(f"  CV R2: {best['cv_r2_mean']:.4f} \u00b1 {best['cv_r2_std']:.4f}")
    print(f"  Test R2: {best['test_r2']:.4f}  Test MAE: {best['test_mae']:.4f}")

    best_model.fit(X, y)

    if best_name == "PolynomialRidge":
        poly = best_model.named_steps["poly"]
        ridge = best_model.named_steps["ridge"]
        names = poly.get_feature_names_out(FEATURE_NAMES)
        print("\nTop coefficients (PolynomialRidge):")
        order = np.argsort(-np.abs(ridge.coef_))[:6]
        for i in order:
            print(f"  {names[i]}: {ridge.coef_[i]:.3f}")
    elif best_name == "LinearRegression":
        print("\nCoefficients:")
        for name, coef in zip(FEATURE_NAMES, best_model.coef_):
            print(f"  {name}: {coef:.3f}")
    else:
        print("\n(NeuralNet selected \u2014 no simple linear feature importances; "
              "accuracy traded for some interpretability.)")

    joblib.dump(best_model, MODEL_PATH)

    meta = {
        "selected_model": best_name,
        "feature_names": FEATURE_NAMES,
        "cv_r2_mean": round(best["cv_r2_mean"], 4),
        "cv_r2_std": round(best["cv_r2_std"], 4),
        "test_r2": round(best["test_r2"], 4),
        "test_mae": round(best["test_mae"], 4),
        "all_models": {n: {"cv_r2_mean": round(r["cv_r2_mean"], 4), "test_r2": round(r["test_r2"], 4), "test_mae": round(r["test_mae"], 4)} for n, r in results.items()}
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved {best_name} to {MODEL_PATH}")
    print(f"Saved comparison metadata to {META_PATH}")


if __name__ == "__main__":
    main()