"""
Unit tests for ML signal model predict.py.
Tests the predict() function with a pre-built toy model fixture
so tests don't require a real trained model on disk.
"""
import json
import os
import pickle
import sys
import tempfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))


def _make_price_df(n: int = 120, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-01", periods=n)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    high = close * 1.01
    low = close * 0.99
    open_ = close * 1.002
    volume = rng.integers(500_000, 2_000_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )


@pytest.fixture
def toy_model_dir(tmp_path, monkeypatch):
    """Create a minimal trained model in a temp directory."""
    from xgboost import XGBRegressor
    from sklearn.preprocessing import StandardScaler
    from app.services.features.engineer import FEATURE_COLS, compute_features

    df = _make_price_df(200)
    feats = compute_features(df)
    X = feats[FEATURE_COLS].values
    y = np.random.default_rng(1).normal(0, 0.01, len(feats))

    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)
    model = XGBRegressor(n_estimators=10, random_state=42, verbosity=0)
    model.fit(X_s, y)

    version = "xgb_test"
    model.save_model(str(tmp_path / f"{version}.json"))
    with open(tmp_path / f"{version}_scaler.pkl", "wb") as f:
        pickle.dump(scaler, f)

    # Patch MODELS_DIR in the predict module
    import app.services.ml.predict as pred_module
    monkeypatch.setattr(pred_module, "MODELS_DIR", tmp_path)
    pred_module._model_cache.clear()
    pred_module._scaler_cache.clear()

    return tmp_path, version


class TestPredict:
    def test_returns_signal_dict(self, toy_model_dir):
        tmp_path, version = toy_model_dir
        from app.services.ml.predict import predict

        df = _make_price_df(120)
        result = predict("AAPL", df, date(2022, 6, 15), model_version=version)

        assert "signal_score" in result
        assert "raw_prediction" in result
        assert "features_snapshot" in result
        assert result["symbol"] == "AAPL"

    def test_signal_score_clamped(self, toy_model_dir):
        _, version = toy_model_dir
        from app.services.ml.predict import predict

        df = _make_price_df(120)
        result = predict("AAPL", df, date(2022, 6, 15), model_version=version)
        assert -3.0 <= result["signal_score"] <= 3.0

    def test_short_series_raises(self, toy_model_dir):
        _, version = toy_model_dir
        from app.services.ml.predict import predict

        df = _make_price_df(10)  # too short for indicators
        with pytest.raises((ValueError, Exception)):
            predict("AAPL", df, date(2022, 1, 20), model_version=version)

    def test_missing_model_raises(self, toy_model_dir):
        _, _ = toy_model_dir
        from app.services.ml.predict import predict, _model_cache, _scaler_cache
        _model_cache.clear()
        _scaler_cache.clear()

        df = _make_price_df(120)
        with pytest.raises(FileNotFoundError):
            predict("AAPL", df, date(2022, 6, 15), model_version="nonexistent_v999")

    def test_batch_predict_skips_failures(self, toy_model_dir):
        _, version = toy_model_dir
        from app.services.ml.predict import batch_predict

        price_dfs = {
            "AAPL": _make_price_df(120, seed=1),
            "BAD": _make_price_df(5, seed=2),   # too short — should be skipped
        }
        results = batch_predict(price_dfs, date(2022, 6, 15), model_version=version)
        assert "AAPL" in results
        assert "BAD" not in results
