"""
ML signal model training pipeline.

Uses walk-forward (expanding window) time-series cross-validation.
Trains XGBRegressor to predict 5-day forward return.
Saves versioned model artifact (JSON) + z-score scaler (pkl) to backend/models/.
"""
import json
import logging
import os
import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

try:
    from xgboost import XGBRegressor
except ImportError:
    raise ImportError("pip install xgboost")

from app.services.features.engineer import FEATURE_COLS, add_forward_return_label, compute_features

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[4] / "models"
MODELS_DIR.mkdir(exist_ok=True)

LABEL_COL = "forward_return_5d"
N_FORWARD = 5  # fixed — do not change after first training run (see plan D2)


def walk_forward_train(
    price_dfs: dict[str, pd.DataFrame],
    model_version: str = "xgb_v1",
    min_train_rows: int = 252,
    val_window: int = 63,
) -> dict:
    """
    Train XGBoost with walk-forward expanding-window validation.

    Args:
        price_dfs: dict mapping symbol → price DataFrame (sorted ascending, columns lowercase)
        model_version: artifact name without extension (e.g. "xgb_v1")
        min_train_rows: minimum rows in first training window
        val_window: size of each validation fold in trading days

    Returns:
        dict with 'model_version', 'val_metrics', 'feature_importance'
    """
    all_feats: list[pd.DataFrame] = []
    for symbol, df in price_dfs.items():
        feats = compute_features(df)
        feats = add_forward_return_label(feats)
        feats["symbol"] = symbol
        all_feats.append(feats)

    if not all_feats:
        raise ValueError("No feature data to train on")

    combined = pd.concat(all_feats).sort_index()

    X = combined[FEATURE_COLS]
    y = combined[LABEL_COL]

    # ── Walk-forward splits ───────────────────────────────────────────────────
    n = len(combined)
    val_metrics: list[dict] = []
    fold = 0

    for split in range(min_train_rows, n - val_window, val_window):
        X_train, y_train = X.iloc[:split], y.iloc[:split]
        X_val, y_val = X.iloc[split : split + val_window], y.iloc[split : split + val_window]

        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_val_s = scaler.transform(X_val)

        model = XGBRegressor(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train_s, y_train)

        preds = model.predict(X_val_s)
        mae = float(np.mean(np.abs(preds - y_val.values)))
        directional_acc = float(np.mean(np.sign(preds) == np.sign(y_val.values)))

        val_metrics.append({"fold": fold, "mae": mae, "directional_accuracy": directional_acc})
        logger.info("Fold %d — MAE=%.4f  DirectAcc=%.3f", fold, mae, directional_acc)
        fold += 1

    if not val_metrics:
        raise ValueError("Not enough data for walk-forward validation")

    # ── Final model trained on ALL data ──────────────────────────────────────
    final_scaler = StandardScaler()
    X_all_s = final_scaler.fit_transform(X)
    final_model = XGBRegressor(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,
    )
    final_model.fit(X_all_s, y)

    # ── Persist artifacts ─────────────────────────────────────────────────────
    model_path = MODELS_DIR / f"{model_version}.json"
    scaler_path = MODELS_DIR / f"{model_version}_scaler.pkl"
    meta_path = MODELS_DIR / f"{model_version}_meta.json"

    final_model.save_model(str(model_path))
    with open(scaler_path, "wb") as f:
        pickle.dump(final_scaler, f)

    avg_mae = float(np.mean([m["mae"] for m in val_metrics]))
    avg_dir = float(np.mean([m["directional_accuracy"] for m in val_metrics]))
    feature_importance = dict(
        zip(FEATURE_COLS, final_model.feature_importances_.tolist())
    )

    meta = {
        "model_version": model_version,
        "n_features": len(FEATURE_COLS),
        "feature_cols": FEATURE_COLS,
        "label": LABEL_COL,
        "n_forward_days": N_FORWARD,
        "val_folds": len(val_metrics),
        "val_avg_mae": avg_mae,
        "val_avg_directional_accuracy": avg_dir,
        "feature_importance": feature_importance,
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info(
        "Training complete — %d folds, avg MAE=%.4f, avg DirectAcc=%.3f",
        len(val_metrics),
        avg_mae,
        avg_dir,
    )
    logger.info("Artifacts saved to %s", MODELS_DIR)

    return meta
