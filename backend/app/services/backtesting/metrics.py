"""
Backtesting performance metrics.
All functions are pure (no side effects) and work on pandas Series or numpy arrays.
"""
import numpy as np
import pandas as pd


def total_return(equity_curve: pd.Series) -> float:
    """Total return from start to end of equity curve."""
    if len(equity_curve) < 2:
        return 0.0
    return float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)


def cagr(equity_curve: pd.Series, trading_days_per_year: int = 252) -> float:
    """Compound annual growth rate."""
    n = len(equity_curve)
    if n < 2:
        return 0.0
    years = n / trading_days_per_year
    if years == 0:
        return 0.0
    tr = total_return(equity_curve)
    return float((1 + tr) ** (1 / years) - 1)


def sharpe_ratio(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.05,
    trading_days_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio using daily portfolio returns."""
    if len(equity_curve) < 2:
        return 0.0
    daily_returns = equity_curve.pct_change().dropna()
    if daily_returns.std() == 0:
        return 0.0
    rf_daily = risk_free_rate / trading_days_per_year
    excess = daily_returns - rf_daily
    return float(excess.mean() / excess.std() * np.sqrt(trading_days_per_year))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a positive fraction (0 = no drawdown)."""
    if len(equity_curve) < 2:
        return 0.0
    rolling_max = equity_curve.cummax()
    drawdowns = (equity_curve - rolling_max) / rolling_max
    return float(abs(drawdowns.min()))


def win_rate(trades: list[dict]) -> float:
    """Fraction of closed trades that were profitable. Returns 0.0 if no trades."""
    closed = [t for t in trades if t.get("pnl") is not None]
    if not closed:
        return 0.0
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return wins / len(closed)


def avg_win_loss(trades: list[dict]) -> dict:
    """Average win and loss amounts."""
    closed = [t for t in trades if t.get("pnl") is not None]
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    return {
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
    }


def compute_all_metrics(
    equity_curve: pd.Series,
    trades: list[dict],
    trading_days_per_year: int = 252,
) -> dict:
    """Compute the full metrics dict stored in BacktestRun.results."""
    wl = avg_win_loss(trades)
    return {
        "total_return": total_return(equity_curve),
        "cagr": cagr(equity_curve, trading_days_per_year),
        "sharpe": sharpe_ratio(equity_curve, trading_days_per_year=trading_days_per_year),
        "max_drawdown": max_drawdown(equity_curve),
        "win_rate": win_rate(trades),
        "avg_win": wl["avg_win"],
        "avg_loss": wl["avg_loss"],
        "num_trades": len(trades),
    }
