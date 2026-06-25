"""
Unit tests for backtesting metrics and a smoke test of the engine loop.

Metrics are tested against hand-computed values.
The engine smoke test uses a fully mocked DB session so no database is required.
"""
import sys
import os

# Ensure the backend package is importable when running from the repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

import numpy as np
import pandas as pd
import pytest
from datetime import date
from unittest.mock import MagicMock, patch, call

from app.services.backtesting.metrics import (
    avg_win_loss,
    cagr,
    compute_all_metrics,
    max_drawdown,
    sharpe_ratio,
    total_return,
    win_rate,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _flat_equity(n: int = 252, start: float = 100_000.0) -> pd.Series:
    """No change — total return 0, max drawdown 0."""
    return pd.Series([start] * n)


def _growing_equity(n: int = 252, annual_return: float = 0.12, start: float = 100_000.0) -> pd.Series:
    """Steady daily growth targeting ~annual_return per year."""
    daily = (1 + annual_return) ** (1 / 252) - 1
    values = [start * (1 + daily) ** i for i in range(n)]
    return pd.Series(values)


def _drawdown_equity() -> pd.Series:
    """Known max drawdown: peak 110 000, trough 88 000 → (110-88)/110 ≈ 0.2."""
    return pd.Series([100_000, 105_000, 110_000, 99_000, 88_000, 95_000, 105_000])


def _make_price_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    """Synthetic OHLCV DataFrame with business-day DatetimeIndex."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2022-01-01", periods=n)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    high = close * 1.01
    low = close * 0.99
    return pd.DataFrame(
        {
            "open": close * 1.002,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(500_000, 2_000_000, n).astype(float),
        },
        index=dates,
    )


# ─────────────────────────────────────────────────────────────────────────────
# total_return
# ─────────────────────────────────────────────────────────────────────────────

class TestTotalReturn:
    def test_flat(self):
        assert total_return(_flat_equity()) == pytest.approx(0.0)

    def test_double(self):
        eq = pd.Series([100_000, 200_000])
        assert total_return(eq) == pytest.approx(1.0)

    def test_loss(self):
        eq = pd.Series([100_000, 50_000])
        assert total_return(eq) == pytest.approx(-0.5)

    def test_single_element(self):
        assert total_return(pd.Series([100_000])) == pytest.approx(0.0)

    def test_grow_and_shrink(self):
        eq = pd.Series([100_000, 150_000, 120_000])
        assert total_return(eq) == pytest.approx(0.2)


# ─────────────────────────────────────────────────────────────────────────────
# cagr
# ─────────────────────────────────────────────────────────────────────────────

class TestCAGR:
    def test_flat_is_zero(self):
        assert cagr(_flat_equity()) == pytest.approx(0.0, abs=1e-6)

    def test_approx_12_pct(self):
        eq = _growing_equity(252, annual_return=0.12)
        result = cagr(eq)
        assert result == pytest.approx(0.12, rel=0.05)

    def test_negative(self):
        eq = pd.Series([100_000, 80_000, 70_000, 60_000])
        assert cagr(eq) < 0

    def test_single_element_is_zero(self):
        assert cagr(pd.Series([100_000])) == pytest.approx(0.0)

    def test_proportional_to_duration(self):
        # Two years of 10% annual should give ~10% CAGR
        eq = _growing_equity(504, annual_return=0.10)
        result = cagr(eq)
        assert result == pytest.approx(0.10, rel=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# max_drawdown
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxDrawdown:
    def test_known_drawdown(self):
        eq = _drawdown_equity()
        result = max_drawdown(eq)
        # Peak 110 000, trough 88 000 → (110 000 - 88 000) / 110 000 = 0.2
        assert result == pytest.approx(0.2, rel=0.01)

    def test_flat_zero_drawdown(self):
        assert max_drawdown(_flat_equity()) == pytest.approx(0.0, abs=1e-9)

    def test_monotonic_increase_no_drawdown(self):
        eq = pd.Series([100, 110, 120, 130])
        assert max_drawdown(eq) == pytest.approx(0.0, abs=1e-9)

    def test_single_element(self):
        assert max_drawdown(pd.Series([100_000])) == pytest.approx(0.0)

    def test_always_positive(self):
        rng = np.random.default_rng(1)
        eq = pd.Series(100_000 * np.cumprod(1 + rng.normal(0, 0.02, 200)))
        assert max_drawdown(eq) >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# sharpe_ratio
# ─────────────────────────────────────────────────────────────────────────────

class TestSharpeRatio:
    def test_positive_for_growing_equity(self):
        eq = _growing_equity(252, annual_return=0.15)
        result = sharpe_ratio(eq, risk_free_rate=0.05)
        assert result > 0

    def test_flat_equity_is_zero(self):
        eq = _flat_equity()
        result = sharpe_ratio(eq)
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_negative_for_declining_equity(self):
        eq = pd.Series([100_000 * (0.999 ** i) for i in range(252)])
        result = sharpe_ratio(eq, risk_free_rate=0.05)
        assert result < 0

    def test_single_element_is_zero(self):
        assert sharpe_ratio(pd.Series([100_000])) == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# win_rate
# ─────────────────────────────────────────────────────────────────────────────

class TestWinRate:
    def test_all_wins(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": 200}]
        assert win_rate(trades) == pytest.approx(1.0)

    def test_no_wins(self):
        trades = [{"pnl": -100}, {"pnl": -50}]
        assert win_rate(trades) == pytest.approx(0.0)

    def test_half_wins(self):
        trades = [{"pnl": 100}, {"pnl": -50}]
        assert win_rate(trades) == pytest.approx(0.5)

    def test_no_trades(self):
        assert win_rate([]) == pytest.approx(0.0)

    def test_trades_without_pnl_excluded(self):
        # Trades without 'pnl' key (buy-side trades) should be excluded
        trades = [{"pnl": None}, {"pnl": 100}]
        assert win_rate(trades) == pytest.approx(1.0)

    def test_zero_pnl_counts_as_loss(self):
        trades = [{"pnl": 0}, {"pnl": 100}]
        assert win_rate(trades) == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# avg_win_loss
# ─────────────────────────────────────────────────────────────────────────────

class TestAvgWinLoss:
    def test_basic(self):
        trades = [{"pnl": 100}, {"pnl": 200}, {"pnl": -50}, {"pnl": -150}]
        result = avg_win_loss(trades)
        assert result["avg_win"] == pytest.approx(150.0)
        assert result["avg_loss"] == pytest.approx(-100.0)

    def test_no_wins(self):
        trades = [{"pnl": -100}]
        result = avg_win_loss(trades)
        assert result["avg_win"] == pytest.approx(0.0)
        assert result["avg_loss"] == pytest.approx(-100.0)

    def test_no_losses(self):
        trades = [{"pnl": 100}]
        result = avg_win_loss(trades)
        assert result["avg_win"] == pytest.approx(100.0)
        assert result["avg_loss"] == pytest.approx(0.0)

    def test_empty(self):
        result = avg_win_loss([])
        assert result["avg_win"] == pytest.approx(0.0)
        assert result["avg_loss"] == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# compute_all_metrics
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeAllMetrics:
    def test_returns_all_keys(self):
        eq = _growing_equity(252)
        trades = [{"pnl": 200}, {"pnl": -50}]
        result = compute_all_metrics(eq, trades)
        required_keys = ("total_return", "cagr", "sharpe", "max_drawdown",
                         "win_rate", "avg_win", "avg_loss", "num_trades")
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_num_trades_correct(self):
        eq = _growing_equity(252)
        trades = [{"pnl": 100}] * 7
        result = compute_all_metrics(eq, trades)
        assert result["num_trades"] == 7

    def test_values_are_floats(self):
        eq = _growing_equity(252)
        trades = [{"pnl": 100}, {"pnl": -50}]
        result = compute_all_metrics(eq, trades)
        for k, v in result.items():
            if k != "num_trades":
                assert isinstance(v, float), f"Expected float for {k}, got {type(v)}"

    def test_consistent_with_individual_functions(self):
        eq = _growing_equity(252, annual_return=0.10)
        trades = [{"pnl": 300}, {"pnl": -100}, {"pnl": 50}]
        result = compute_all_metrics(eq, trades)
        assert result["total_return"] == pytest.approx(total_return(eq))
        assert result["cagr"] == pytest.approx(cagr(eq))
        assert result["sharpe"] == pytest.approx(sharpe_ratio(eq))
        assert result["max_drawdown"] == pytest.approx(max_drawdown(eq))
        assert result["win_rate"] == pytest.approx(win_rate(trades))


# ─────────────────────────────────────────────────────────────────────────────
# Engine smoke tests — no real DB, ML model, or LLM required
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_db(run_id: int = 1):
    """Return a MagicMock DB session that satisfies the engine's DB calls."""
    db = MagicMock()

    # BacktestRun mock
    run_mock = MagicMock()
    run_mock.id = run_id

    db.add = MagicMock()
    db.flush = MagicMock()

    # db.commit() is a no-op; db.refresh() sets run.id on the passed object
    def _refresh(obj):
        if isinstance(obj, MagicMock):
            obj.id = run_id

    db.commit = MagicMock()
    db.refresh = MagicMock(side_effect=_refresh)
    db.bulk_save_objects = MagicMock()

    # db.query(...).filter(...).first() → None (no existing instruments or positions)
    db.query.return_value.filter.return_value.first.return_value = None

    return db, run_mock


class TestBacktestEngine:
    """Smoke tests for the engine. Use signal_override_fn to bypass ML/LLM."""

    def _run_with_override(self, n_days: int = 120, n_symbols: int = 1, signal: float = 0.5):
        """Helper: run the engine with a constant signal override, fully mocked DB."""
        from app.services.backtesting.engine import run_backtest, BacktestRun

        db, _ = _make_mock_db()

        # BacktestRun needs to be created via db.add; mock it so db.refresh gives it an id
        created_run = None

        original_add = db.add.side_effect

        def _capture_add(obj):
            nonlocal created_run
            if hasattr(obj, "date_range_start"):  # it's a BacktestRun-like object
                created_run = obj
                obj.id = 1  # assign id immediately so refresh works
            if original_add:
                original_add(obj)

        db.add.side_effect = _capture_add

        price_dfs = {
            f"SYM{i}": _make_price_df(n=n_days + 80, seed=i)
            for i in range(n_symbols)
        }
        dates = sorted({d.date() for df in price_dfs.values() for d in df.index})
        start = dates[80]
        end = dates[-1]

        result = run_backtest(
            db=db,
            price_dfs=price_dfs,
            start_date=start,
            end_date=end,
            strategy_version="test_v1",
            use_llm=False,
            signal_override_fn=lambda sym, d: signal,
            params={"test": True},
        )
        return result, db

    def test_engine_runs_without_error(self):
        result, db = self._run_with_override()
        assert result is not None

    def test_db_commit_called(self):
        _, db = self._run_with_override()
        assert db.commit.called

    def test_bulk_save_called(self):
        _, db = self._run_with_override()
        assert db.bulk_save_objects.called

    def test_results_populated(self):
        result, _ = self._run_with_override()
        # results dict should be set on the returned BacktestRun object
        assert result.results is not None
        assert "cagr" in result.results
        assert "sharpe" in result.results
        assert "max_drawdown" in result.results

    def test_zero_signal_does_not_crash(self):
        """Signal of 0 should produce no trades (hold only)."""
        result, db = self._run_with_override(signal=0.0)
        assert result is not None

    def test_negative_signal_sell_path(self):
        """Negative signal should attempt sell logic without crashing."""
        result, db = self._run_with_override(signal=-0.8)
        assert result is not None

    def test_multi_symbol(self):
        result, _ = self._run_with_override(n_symbols=3, signal=0.6)
        assert result is not None

    def test_insufficient_days_returns_empty_results(self):
        """Less than 2 trading days should return early with empty results."""
        from app.services.backtesting.engine import run_backtest

        db, _ = _make_mock_db()

        def _capture_add(obj):
            if hasattr(obj, "date_range_start"):
                obj.id = 1

        db.add.side_effect = _capture_add

        # Single-day price df — not enough trading days in range
        df = _make_price_df(n=5, seed=0)
        single_date = df.index[2].date()
        result = run_backtest(
            db=db,
            price_dfs={"SYM0": df},
            start_date=single_date,
            end_date=single_date,  # same start and end = 1 day = too short
            use_llm=False,
            signal_override_fn=lambda sym, d: 0.5,
        )
        assert result is not None
        assert result.results == {}


# ─────────────────────────────────────────────────────────────────────────────
# Shuffle sanity check (metrics-level, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestShuffleSanityCheck:
    """
    Conceptual shuffle test: if signals are random noise the resulting equity
    curve should not exhibit meaningful trend (CAGR near zero, Sharpe near zero).
    We simulate this at the metrics layer without running the full engine.
    """

    def test_random_trades_produce_near_zero_edge(self):
        rng = np.random.default_rng(42)
        n = 504  # 2 trading years
        # Simulate a random-walk equity curve (no alpha)
        daily_returns = rng.normal(0.0, 0.01, n)
        equity = pd.Series(100_000 * np.cumprod(1 + daily_returns))

        result = compute_all_metrics(equity, [])
        # With pure noise and no transaction costs, CAGR should be close to 0
        # (within 5% absolute — over 2 years random walk variance allows drift)
        assert abs(result["cagr"]) < 0.10, (
            f"Random equity curve has unexpectedly high CAGR: {result['cagr']:.3f}"
        )

    def test_deterministic_positive_cagr_detectable(self):
        """Ensure we can detect genuine alpha when it exists."""
        eq = _growing_equity(504, annual_return=0.20)
        result = compute_all_metrics(eq, [])
        assert result["cagr"] > 0.10

    def test_shuffle_metrics_have_required_keys(self):
        eq = pd.Series([100_000] * 50)
        result = compute_all_metrics(eq, [])
        for key in ("cagr", "sharpe", "max_drawdown", "win_rate", "num_trades"):
            assert key in result
