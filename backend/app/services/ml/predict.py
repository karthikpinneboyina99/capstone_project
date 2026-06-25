"""
ML signal model inference.

The predict() function is the single source of truth used by both the
backtester and the live paper-trading executor. They must NEVER diverge.
"""
import json
import logging
import pickle
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.features.engineer import FEATURE_COLS, compute_features

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[4] / "models"

# Module-level cache so we don't reload the model on every call
_model_cache: dict[str, object] = {}
_scaler_cache: dict[str, object] = {}


def _load_model(model_version: str):
    if model_version not in _model_cache:
        try:
            from xgboost import XGBRegressor
        except ImportError:
            raise ImportError("pip install xgboost")

        model_path = MODELS_DIR / f"{model_version}.json"
        scaler_path = MODELS_DIR / f"{model_version}_scaler.pkl"

        if not model_path.exists():
            raise FileNotFoundError(f"Model artifact not found: {model_path}")
        if not scaler_path.exists():
            raise FileNotFoundError(f"Scaler artifact not found: {scaler_path}")

        m = XGBRegressor()
        m.load_model(str(model_path))
        _model_cache[model_version] = m

        with open(scaler_path, "rb") as f:
            _scaler_cache[model_version] = pickle.load(f)

    return _model_cache[model_version], _scaler_cache[model_version]


def predict(
    symbol: str,
    price_df: pd.DataFrame,
    as_of_date: date,
    model_version: str = "xgb_v1",
) -> dict:
    """
    Generate a signal score for (symbol, as_of_date).

    INVARIANT: only uses price_df rows with date <= as_of_date.
    The caller is responsible for passing only available data — this function
    does NOT filter by date itself to allow the backtester to pass pre-sliced data.

    Returns:
        {
            "symbol": str,
            "as_of_date": date,
            "model_version": str,
            "signal_score": float,   # z-score normalised, clamped to [-3, 3]
            "raw_prediction": float, # unnormalised predicted 5d return
            "features_snapshot": dict,  # feature values used (for auditability)
        }
    Raises ValueError if there is not enough data to compute features.
    """
    model, scaler = _load_model(model_version)

    feats_df = compute_features(price_df)

    if feats_df.empty:
        raise ValueError(f"Not enough data to compute features for {symbol} on {as_of_date}")

    # Use the LAST row (most recent available as of as_of_date)
    last_row = feats_df[FEATURE_COLS].iloc[[-1]]
    feature_values = last_row.iloc[0].to_dict()

    X_scaled = scaler.transform(last_row)
    raw_pred = float(model.predict(X_scaled)[0])

    # Normalise to a z-score signal using a rolling window of past predictions
    # For single-row inference we use the raw prediction clamped to [-3, 3]
    # The backtester computes proper z-scores across the full backtest window.
    signal_score = float(np.clip(raw_pred * 100, -3.0, 3.0))  # rough normalisation

    return {
        "symbol": symbol,
        "as_of_date": as_of_date,
        "model_version": model_version,
        "signal_score": signal_score,
        "raw_prediction": raw_pred,
        "features_snapshot": {k: round(v, 6) for k, v in feature_values.items()},
    }


def batch_predict(
    price_dfs: dict[str, pd.DataFrame],
    as_of_date: date,
    model_version: str = "xgb_v1",
) -> dict[str, dict]:
    """
    Generate signals for multiple symbols at once.
    Skips symbols where prediction fails (logs warning).
    Returns dict mapping symbol -> predict() result.
    """
    results: dict[str, dict] = {}
    for symbol, df in price_dfs.items():
        try:
            results[symbol] = predict(symbol, df, as_of_date, model_version)
        except Exception as exc:
            logger.warning("Prediction failed for %s on %s: %s", symbol, as_of_date, exc)
    return results
