"""
Thin wrapper around alpaca-py for paper orders only.
Never submit to the live endpoint.
"""
from __future__ import annotations
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

_PAPER_URL = "https://paper-api.alpaca.markets"


class AlpacaPaperClient:
    def __init__(self):
        if settings.ALPACA_BASE_URL != _PAPER_URL:
            raise RuntimeError(
                f"AlpacaPaperClient refuses to connect to '{settings.ALPACA_BASE_URL}'. "
                f"Must be '{_PAPER_URL}'."
            )
        _key = settings.ALPACA_API_KEY or ""
        _secret = settings.ALPACA_SECRET_KEY or ""
        _placeholder = {"", "your_alpaca_paper_key_id", "your_alpaca_paper_secret_key"}
        if _key in _placeholder or _secret in _placeholder:
            logger.info("Alpaca keys not configured — running in simulation mode (all trades are local)")
            self._available = False
            return
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce
            self._client = TradingClient(
                api_key=_key,
                secret_key=_secret,
                paper=True,
            )
            self._MarketOrderRequest = MarketOrderRequest
            self._OrderSide = OrderSide
            self._TimeInForce = TimeInForce
            self._available = True
        except ImportError:
            logger.warning("alpaca-py not installed — running in simulation mode")
            self._available = False

    def get_account(self) -> dict:
        if not self._available:
            return {"cash": 100_000.0, "portfolio_value": 100_000.0, "equity": 0.0}
        acct = self._client.get_account()
        return {
            "cash": float(acct.cash),
            "portfolio_value": float(acct.portfolio_value),
            "equity": float(acct.portfolio_value) - float(acct.cash),
        }

    def get_positions(self) -> list[dict]:
        if not self._available:
            return []
        positions = self._client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
        ]

    def submit_market_buy(self, symbol: str, notional: float) -> dict | None:
        """Submit a notional market buy order. Returns order dict or None on failure."""
        if not self._available:
            logger.info("[STUB] BUY %s notional=%.2f", symbol, notional)
            return {"id": "stub", "symbol": symbol, "side": "buy", "notional": notional}
        try:
            req = self._MarketOrderRequest(
                symbol=symbol,
                notional=round(notional, 2),
                side=self._OrderSide.BUY,
                time_in_force=self._TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            logger.info("BUY order submitted: %s notional=%.2f id=%s", symbol, notional, order.id)
            return {"id": str(order.id), "symbol": symbol, "side": "buy", "notional": notional}
        except Exception as exc:
            logger.error("BUY order failed for %s: %s", symbol, exc)
            return None

    def submit_market_sell(self, symbol: str, qty: float) -> dict | None:
        """Submit a quantity-based market sell order. Returns order dict or None on failure."""
        if not self._available:
            logger.info("[STUB] SELL %s qty=%.4f", symbol, qty)
            return {"id": "stub", "symbol": symbol, "side": "sell", "qty": qty}
        try:
            req = self._MarketOrderRequest(
                symbol=symbol,
                qty=round(qty, 4),
                side=self._OrderSide.SELL,
                time_in_force=self._TimeInForce.DAY,
            )
            order = self._client.submit_order(req)
            logger.info("SELL order submitted: %s qty=%.4f id=%s", symbol, qty, order.id)
            return {"id": str(order.id), "symbol": symbol, "side": "sell", "qty": qty}
        except Exception as exc:
            logger.error("SELL order failed for %s: %s", symbol, exc)
            return None

    def close_position(self, symbol: str) -> bool:
        """Close an entire position. Returns True if successful."""
        if not self._available:
            logger.info("[STUB] CLOSE %s", symbol)
            return True
        try:
            self._client.close_position(symbol)
            return True
        except Exception as exc:
            logger.error("close_position failed for %s: %s", symbol, exc)
            return False
