"""
Simulation API endpoint tests using FastAPI TestClient + an in-memory SQLite DB.
All simulation records use mode="simulation".
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# ── In-memory SQLite setup ────────────────────────────────────────────────────

TEST_DB_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    yield
    with engine.begin() as conn:
        Base.metadata.drop_all(conn)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_account_fresh_state(client):
    """GET /simulation/account should return $100k on a clean slate."""
    resp = client.get("/simulation/account")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 100_000.0
    assert data["equity"] == 0.0
    assert data["total_value"] == 100_000.0
    assert data["return_pct"] == 0.0
    assert data["pnl"] == 0.0
    assert data["trade_count"] == 0


def test_positions_empty(client):
    """GET /simulation/positions should return empty list initially."""
    resp = client.get("/simulation/positions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_trades_empty(client):
    """GET /simulation/trades should return empty list initially."""
    resp = client.get("/simulation/trades")
    assert resp.status_code == 200
    assert resp.json() == []


def test_buy_creates_trade_and_position(client):
    """POST /simulation/buy should create a Trade and Position."""
    resp = client.post(
        "/simulation/buy",
        json={"symbol": "AAPL", "quantity": 10, "price": 150.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["symbol"] == "AAPL"
    assert data["side"] == "buy"
    assert data["quantity"] == 10
    assert data["price"] == 150.0
    assert data["position_quantity"] == 10
    assert data["avg_entry_price"] == 150.0

    # Account should reflect the purchase
    account = client.get("/simulation/account").json()
    assert account["cash"] == 100_000.0 - (10 * 150.0)
    assert account["trade_count"] == 1

    # Position should appear
    positions = client.get("/simulation/positions").json()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "AAPL"
    assert positions[0]["quantity"] == 10

    # Trade should appear
    trades = client.get("/simulation/trades").json()
    assert len(trades) == 1
    assert trades[0]["side"] == "buy"


def test_sell_reduces_position(client):
    """POST /simulation/sell should reduce the position quantity."""
    # First buy
    client.post(
        "/simulation/buy",
        json={"symbol": "MSFT", "quantity": 20, "price": 300.0},
    )

    # Then sell half
    resp = client.post(
        "/simulation/sell",
        json={"symbol": "MSFT", "quantity": 10, "price": 310.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["position_quantity"] == 10
    assert data["side"] == "sell"

    # Cash should be: 100k - 20*300 + 10*310 = 100k - 6000 + 3100 = 97100
    account = client.get("/simulation/account").json()
    assert account["cash"] == pytest.approx(97_100.0)
    assert account["trade_count"] == 2


def test_sell_insufficient_position(client):
    """POST /simulation/sell without sufficient position should return 400."""
    resp = client.post(
        "/simulation/sell",
        json={"symbol": "AAPL", "quantity": 5, "price": 150.0},
    )
    assert resp.status_code == 400
    assert "Insufficient" in resp.json()["detail"]


def test_buy_insufficient_cash(client):
    """POST /simulation/buy that exceeds cash should return 400."""
    resp = client.post(
        "/simulation/buy",
        # 100k shares at $2 = $200k > $100k starting cash
        json={"symbol": "AAPL", "quantity": 100_000, "price": 2.0},
    )
    assert resp.status_code == 400
    assert "Insufficient cash" in resp.json()["detail"]


def test_reset_clears_everything(client):
    """POST /simulation/reset should clear all trades and positions."""
    # Buy some stocks first
    client.post("/simulation/buy", json={"symbol": "AAPL", "quantity": 5, "price": 150.0})
    client.post("/simulation/buy", json={"symbol": "MSFT", "quantity": 3, "price": 300.0})

    # Confirm they exist
    assert len(client.get("/simulation/trades").json()) == 2
    assert len(client.get("/simulation/positions").json()) == 2

    # Reset
    resp = client.post("/simulation/reset")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "reset"
    assert data["cash"] == 100_000.0

    # Everything should be cleared
    assert client.get("/simulation/trades").json() == []
    assert client.get("/simulation/positions").json() == []
    account = client.get("/simulation/account").json()
    assert account["cash"] == 100_000.0
    assert account["trade_count"] == 0


def test_buy_unknown_symbol_creates_instrument(client):
    """POST /simulation/buy with a new symbol should create the Instrument row."""
    resp = client.post(
        "/simulation/buy",
        json={"symbol": "XYZ", "quantity": 1, "price": 50.0},
    )
    assert resp.status_code == 200
    assert resp.json()["symbol"] == "XYZ"

    # Instrument should now exist
    resp2 = client.get("/instruments/XYZ")
    assert resp2.status_code == 200
    assert resp2.json()["symbol"] == "XYZ"


def test_buy_multiple_creates_correct_avg_entry(client):
    """Two buys at different prices should produce correct average entry."""
    client.post("/simulation/buy", json={"symbol": "NVDA", "quantity": 10, "price": 400.0})
    client.post("/simulation/buy", json={"symbol": "NVDA", "quantity": 10, "price": 600.0})

    positions = client.get("/simulation/positions").json()
    nvda = next(p for p in positions if p["symbol"] == "NVDA")
    assert nvda["quantity"] == 20
    assert nvda["avg_entry_price"] == pytest.approx(500.0)


def test_close_position(client):
    """POST /simulation/close/{symbol} should sell entire position."""
    client.post("/simulation/buy", json={"symbol": "SPY", "quantity": 5, "price": 400.0})

    # Patch get_price so close can get a price
    with patch("app.api.routers.simulation.get_price", return_value=420.0):
        resp = client.post("/simulation/close/SPY")
    assert resp.status_code == 200
    data = resp.json()
    assert data["position_quantity"] == 0
    assert data["quantity"] == 5

    positions = client.get("/simulation/positions").json()
    assert all(p["symbol"] != "SPY" for p in positions)


def test_close_nonexistent_position(client):
    """POST /simulation/close for a symbol with no position should 404."""
    resp = client.post("/simulation/close/FAKE")
    assert resp.status_code == 404


def test_ai_suggest_mocked(client):
    """POST /simulation/ai/suggest should parse LLM JSON and return suggestions."""
    mock_response_data = {
        "suggestions": [
            {"symbol": "AAPL", "action": "buy", "quantity": 5, "reason": "momentum"},
            {"symbol": "SPY", "action": "buy", "quantity": 3, "reason": "stability"},
        ]
    }

    mock_completion = MagicMock()
    mock_completion.choices[0].message.content = json.dumps(mock_response_data)

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("openai.OpenAI", return_value=mock_client):
        resp = client.post("/simulation/ai/suggest")

    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data
    assert len(data["suggestions"]) == 2
    assert data["suggestions"][0]["symbol"] == "AAPL"
    assert data["suggestions"][1]["symbol"] == "SPY"


def test_ai_suggest_llm_failure(client):
    """POST /simulation/ai/suggest should return 502 if LLM call fails."""
    with patch("openai.OpenAI", side_effect=Exception("LLM down")):
        resp = client.post("/simulation/ai/suggest")
    assert resp.status_code == 502


def test_account_equity_with_position(client):
    """Equity should reflect open position value when prices are available."""
    client.post("/simulation/buy", json={"symbol": "AAPL", "quantity": 10, "price": 150.0})

    # Without prices in shared state, equity uses avg_entry_price as fallback
    account = client.get("/simulation/account").json()
    # cash = 100k - 1500 = 98500, equity = 10 * 150 = 1500 (fallback)
    assert account["cash"] == pytest.approx(98_500.0)
    assert account["total_value"] == pytest.approx(100_000.0)
