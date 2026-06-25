"""
API endpoint tests using FastAPI TestClient + an in-memory SQLite DB.
These are integration tests at the HTTP level, with no real Postgres needed.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Use SQLite in-memory for tests (no Postgres needed)
TEST_DB_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # all "connections" share the same in-memory DB
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


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_instruments_empty(client):
    resp = client.get("/instruments/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_portfolio_summary_default(client):
    resp = client.get("/portfolio/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["cash"] == 100_000.0
    assert data["total_value"] == 100_000.0


def test_positions_empty(client):
    resp = client.get("/portfolio/positions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_trades_empty(client):
    resp = client.get("/trades/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_signals_today_empty(client):
    resp = client.get("/signals/today")
    assert resp.status_code == 200
    assert resp.json() == []


def test_decisions_today_empty(client):
    resp = client.get("/decisions/today")
    assert resp.status_code == 200
    assert resp.json() == []


def test_backtests_empty(client):
    resp = client.get("/backtests/")
    assert resp.status_code == 200
    assert resp.json() == []


def test_instrument_not_found(client):
    resp = client.get("/instruments/FAKE")
    assert resp.status_code == 404


def test_backtest_trigger(client):
    payload = {
        "date_range_start": "2023-01-01",
        "date_range_end": "2023-12-31",
        "strategy_version": "v1",
    }
    resp = client.post("/backtests/trigger", json=payload)
    assert resp.status_code == 202
    data = resp.json()
    assert data["id"] == 1
    assert data["strategy_version"] == "v1"
