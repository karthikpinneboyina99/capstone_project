"""
Feature engineering for the AI Trading Workstation.

All functions are pure (no side effects, no DB access).
Input: a price DataFrame with columns [open, high, low, close, volume]
       indexed by date (or with a 'date' column), sorted ascending.
Output: a DataFrame of features, NaN rows dropped.

Key invariant: features for row D only use data from rows with date <= D.
"""
import numpy as np
import pandas as pd

try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD, EMAIndicator, SMAIndicator
    from ta.volatility import BollingerBands
except ImportError:
    raise ImportError("pip install ta")


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the full feature set from a price DataFrame.

    Args:
        df: DataFrame with columns [open, high, low, close, volume].
            Must be sorted ascending by date with at least 60 rows for all
            indicators to have warmup data. Extra columns are ignored.

    Returns:
        DataFrame with feature columns and the original index, NaN rows dropped.
        Also includes 'close' and 'date' columns for downstream use.
    """
    df = df.copy()

    # Normalise column names to lowercase
    df.columns = [c.lower() for c in df.columns]

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"].astype(float)

    feats = pd.DataFrame(index=df.index)

    # ── Returns ───────────────────────────────────────────────────────────────
    feats["ret_1d"] = close.pct_change(1)
    feats["ret_5d"] = close.pct_change(5)
    feats["ret_20d"] = close.pct_change(20)

    # ── Simple moving averages + price relative to each ───────────────────────
    for window in (10, 20, 50):
        sma = SMAIndicator(close=close, window=window).sma_indicator()
        feats[f"sma{window}"] = sma
        feats[f"price_to_sma{window}"] = close / sma - 1

    # ── Exponential moving averages ───────────────────────────────────────────
    ema12 = EMAIndicator(close=close, window=12).ema_indicator()
    ema26 = EMAIndicator(close=close, window=26).ema_indicator()
    feats["price_to_ema12"] = close / ema12 - 1
    feats["price_to_ema26"] = close / ema26 - 1

    # ── RSI ───────────────────────────────────────────────────────────────────
    feats["rsi14"] = RSIIndicator(close=close, window=14).rsi()

    # ── MACD ──────────────────────────────────────────────────────────────────
    macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    feats["macd_line"] = macd_ind.macd()
    feats["macd_signal"] = macd_ind.macd_signal()
    feats["macd_hist"] = macd_ind.macd_diff()

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb = BollingerBands(close=close, window=20, window_dev=2)
    feats["bb_pct_b"] = bb.bollinger_pband()
    feats["bb_bandwidth"] = bb.bollinger_wband()

    # ── Rolling volatility ────────────────────────────────────────────────────
    feats["volatility_20d"] = feats["ret_1d"].rolling(20).std()

    # ── Volume z-score (strictly lagged — day D excluded from its own mean/std)
    vol_mean = volume.shift(1).rolling(20).mean()
    vol_std = volume.shift(1).rolling(20).std()
    feats["volume_zscore"] = (volume - vol_mean) / vol_std.replace(0, np.nan)

    # ── Day-of-week (0=Monday … 4=Friday) ────────────────────────────────────
    if hasattr(df.index, "dayofweek"):
        feats["day_of_week"] = df.index.dayofweek.astype(float)
    else:
        feats["day_of_week"] = 0.0

    # Preserve close for label computation downstream
    feats["close"] = close

    # Drop warmup NaN rows — never forward-fill
    feats = feats.dropna()

    return feats


# Feature column names (everything except 'close')
FEATURE_COLS = [
    "ret_1d", "ret_5d", "ret_20d",
    "sma10", "sma20", "sma50",
    "price_to_sma10", "price_to_sma20", "price_to_sma50",
    "price_to_ema12", "price_to_ema26",
    "rsi14",
    "macd_line", "macd_signal", "macd_hist",
    "bb_pct_b", "bb_bandwidth",
    "volatility_20d",
    "volume_zscore",
    "day_of_week",
]


def add_forward_return_label(feats: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """
    Add forward_return_5d column (label for training).
    Rows where the label is NaN (last n rows) are dropped.
    ONLY call this during training — never during inference.
    """
    feats = feats.copy()
    feats["forward_return_5d"] = feats["close"].pct_change(n).shift(-n)
    feats = feats.dropna(subset=["forward_return_5d"])
    return feats
