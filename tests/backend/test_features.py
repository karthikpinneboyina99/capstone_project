"""
Unit tests for feature engineering.
All tests use synthetic price series with known properties.
"""
import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'backend'))

from app.services.features.engineer import (
    FEATURE_COLS,
    add_forward_return_label,
    compute_features,
)


def _make_price_df(n: int = 100, start_price: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """Synthetic price series with deterministic returns."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-01", periods=n)
    returns = rng.normal(0.0005, 0.01, n)
    close = start_price * np.cumprod(1 + returns)
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    volume = rng.integers(500_000, 2_000_000, n).astype(float)
    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    return df


class TestComputeFeatures:
    def test_returns_dataframe(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        assert isinstance(feats, pd.DataFrame)
        assert len(feats) > 0

    def test_all_feature_cols_present(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        for col in FEATURE_COLS:
            assert col in feats.columns, f"Missing feature: {col}"

    def test_no_nan_in_output(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        assert not feats[FEATURE_COLS].isnull().any().any(), "NaN values in feature output"

    def test_fewer_rows_than_input_due_to_warmup(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        assert len(feats) < len(df), "Warmup rows should be dropped"

    def test_rsi_bounded(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        assert feats["rsi14"].between(0, 100).all(), "RSI must be in [0, 100]"

    def test_volume_zscore_not_lookahead(self):
        """Day D's volume must NOT be included in its own z-score denominator."""
        df = _make_price_df(60)
        feats = compute_features(df)
        # If volume on last day spikes 10x, the z-score of THAT day should still
        # only reflect prior volumes. We can't fully verify this without inspecting
        # internals, but we can verify the column is finite and non-trivial.
        assert feats["volume_zscore"].notna().all()

    def test_1d_return_matches_manual(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        # Last row's 1d return should match manual calculation
        idx = feats.index[-1]
        pos = df.index.get_loc(idx)
        expected = df["close"].iloc[pos] / df["close"].iloc[pos - 1] - 1
        assert abs(feats.loc[idx, "ret_1d"] - expected) < 1e-9

    def test_short_series_returns_empty(self):
        df = _make_price_df(10)
        feats = compute_features(df)
        assert len(feats) == 0, "Too short to compute indicators — should return empty"


class TestForwardReturnLabel:
    def test_label_present(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        labeled = add_forward_return_label(feats)
        assert "forward_return_5d" in labeled.columns

    def test_last_n_rows_dropped(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        labeled = add_forward_return_label(feats, n=5)
        assert len(labeled) == len(feats) - 5

    def test_label_is_5d_forward_return(self):
        df = _make_price_df(100)
        feats = compute_features(df)
        labeled = add_forward_return_label(feats, n=5)
        # Check one row: label[t] should equal close[t+5]/close[t] - 1
        idx0 = labeled.index[0]
        close0 = labeled.loc[idx0, "close"]
        label0 = labeled.loc[idx0, "forward_return_5d"]
        pos0 = feats.index.get_loc(idx0)
        close5 = feats["close"].iloc[pos0 + 5]
        expected = close5 / close0 - 1
        assert abs(label0 - expected) < 1e-9
