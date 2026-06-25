# Testing Patterns

**Analysis Date:** 2026-06-25

## Test Framework

**Runner:**
- `pytest` (version unpinned in `backend/requirements.txt`)
- `pytest-asyncio` available for async route tests (not yet used)
- Config: no `pytest.ini` or `pyproject.toml` — uses implicit discovery
- `httpx` available for FastAPI `TestClient` integration tests (not yet written)

**Assertion Library:**
- pytest built-in `assert` statements
- `pytest.approx` for floating-point comparisons
- `pytest.raises` for expected exceptions
- `pd.testing.assert_frame_equal` for DataFrame equality

**Run Commands:**
```bash
# From project root
pytest tests/                    # Run all tests
pytest tests/backend/            # Backend tests only
pytest tests/backend/test_market_simulator.py  # Single file
pytest -v tests/                 # Verbose output
pytest -k "TestRetryLogic"       # Run by class name
```

## Test File Organization

**Location:** Separate `tests/` tree at project root, mirroring `backend/app/` structure

```
tests/
├── __init__.py
├── backend/
│   ├── __init__.py
│   ├── test_market_interface.py    # tests for backend/app/services/data_ingestion/market_interface.py
│   ├── test_market_simulator.py    # tests for backend/app/services/data_ingestion/market_simulator.py
│   ├── test_massive_provider.py    # tests for backend/app/services/data_ingestion/massive_provider.py
│   └── test_simulator_provider.py  # tests for backend/app/services/data_ingestion/simulator_provider.py
conftest.py                         # Root conftest — patches sys.path so tests use app.* imports
```

**Naming convention:** `test_<module_name>.py` — one test file per source module.

## sys.path Configuration

**`conftest.py`** at project root:
```python
"""Root conftest.py — adds backend/ to sys.path so tests can import from app.*"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
```
This allows test files to use `from app.services.data_ingestion.market_interface import Bar` without installing the package.

## Test Structure

**Suite Organization:** Grouped into classes by feature/scenario. One class = one behavior area:
```python
class TestSchema:
    def test_correct_columns(self): ...
    def test_non_empty_for_valid_range(self): ...
    def test_date_column_is_datetime(self): ...

class TestOHLCInvariants:
    def setup_method(self):
        self.df = SIM.get_bars("MSFT", date(2022, 1, 1), date(2022, 12, 31))
    def test_high_gte_open(self): ...
    def test_low_lte_close(self): ...
```

**Section separators used in test files:**
```python
# ---------------------------------------------------------------------------
# TestSuiteName
# ---------------------------------------------------------------------------
```

**Setup patterns:**
- `setup_method(self)`: used for per-test setup within a class (e.g., `TestOHLCInvariants`)
- Module-level shared instances: `SIM = MarketSimulator(db_session=None, seed=42)` — reused across suites when deterministic
- `@pytest.fixture`: used in `test_massive_provider.py` for provider instantiation

**No teardown observed** — tests are stateless and use mocks/GBM synthetic data.

## Mocking

**Framework:** `unittest.mock` — `MagicMock`, `patch`, `call`

**HTTP mocking pattern (MassiveProvider):**
```python
from unittest.mock import MagicMock, patch

def _mock_response(body: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body
    resp.raise_for_status = MagicMock()
    return resp

def test_returns_dataframe_for_each_ticker(self, provider):
    resp = _mock_response(_aggs_response())
    with patch("requests.get", return_value=resp):
        result = provider.get_bars(["AAPL", "MSFT"], date(2023, 1, 1), date(2023, 3, 31))
    assert set(result.keys()) == {"AAPL", "MSFT"}
```

**Database mocking pattern (SimulatorProvider / MarketSimulator):**
```python
def _make_mock_session(self, rows):
    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = rows
    return mock_session

def test_db_rows_returned_when_available(self):
    rows = [
        (pd.Timestamp("2023-01-03", tz="UTC"), 150.0, 155.0, 149.0, 153.5, 1_000_000),
    ]
    mock_session = self._make_mock_session(rows)
    sim = MarketSimulator(db_session=mock_session, seed=42)
    df = sim.get_bars("AAPL", date(2023, 1, 1), date(2023, 1, 31))
    assert len(df) == 2
```

**Environment variable mocking:**
```python
def test_returns_simulator_without_key(self, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    provider = create_provider()
    assert isinstance(provider, SimulatorProvider)

def test_returns_massive_with_key(self, monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "fake_key_for_test")
    provider = create_provider()
    assert isinstance(provider, MassiveProvider)
```
Use `monkeypatch` (pytest builtin) for env vars — never `os.environ` directly in tests.

**Sleeping suppressed in retry tests:**
```python
with patch("requests.get", side_effect=responses), \
     patch("time.sleep"):  # don't actually sleep in tests
    result = provider.get_bars(...)
```

**What to mock:**
- All outbound HTTP calls (`requests.get`) — never make real API calls in unit tests
- SQLAlchemy `Session.execute()` — mock at the session level
- `time.sleep` in retry loops — always patch to prevent slow tests
- Environment variables — use `monkeypatch` fixture

**What NOT to mock:**
- `MarketSimulator` internals when testing `SimulatorProvider` — test through the real object
- pandas/numpy — use real data manipulation
- `dataclasses` module — test real frozen behavior

## Fixtures

**Module-level shared instances (deterministic, reused across tests):**
```python
# test_market_simulator.py
SIM = MarketSimulator(db_session=None, seed=42)

# test_simulator_provider.py
PROVIDER = SimulatorProvider(db_session=None, seed=42)
```

**Pytest fixtures (function-scoped, default):**
```python
# test_massive_provider.py
@pytest.fixture
def provider():
    return MassiveProvider(api_key="test_api_key")
```

**Helper builder functions (not fixtures):**
```python
def _bar_result(t_ms=1672531200000, o=150.0, h=155.0, l=149.0, c=153.5, v=82_000_000, vw=152.7):
    return {"t": t_ms, "o": o, "h": h, "l": l, "c": c, "v": v, "vw": vw}

def _aggs_response(bars=None, next_url=None):
    body = {"status": "OK", "results": bars or [_bar_result()]}
    if next_url:
        body["next_url"] = next_url
    return body
```
Use module-level helper functions (prefixed `_`) for building test payloads rather than defining them inline.

**`EXPECTED_COLS` constant** shared within test files to avoid repeating column lists:
```python
EXPECTED_COLS = ["date", "open", "high", "low", "close", "volume", "vwap"]
```

## Coverage

**Requirements:** Not enforced (no `pytest-cov` config, no coverage gate)

**Actual coverage:** The 4 test files cover 100% of the `data_ingestion` package surface area:
- `market_interface.py` → `test_market_interface.py` (dataclasses + factory)
- `market_simulator.py` → `test_market_simulator.py` (GBM + DB replay)
- `massive_provider.py` → `test_massive_provider.py` (HTTP + pagination + retry)
- `simulator_provider.py` → `test_simulator_provider.py` (interface delegation)

## Test Types

**Unit Tests:**
- Scope: individual classes/methods in isolation
- All 4 test files are unit tests
- External dependencies (HTTP, DB) always mocked
- 256 tests total (per MEMORY.md)

**Integration Tests:**
- `httpx` available in requirements but no integration tests written yet
- FastAPI `TestClient` tests not present — planned for API router phases

**E2E Tests:**
- Not used

## Common Patterns

**Floating-point comparisons:**
```python
assert row["open"] == pytest.approx(150.0)
assert df.iloc[0]["close"] == pytest.approx(153.5)
```
Always use `pytest.approx` for float fields, not `==`.

**Frozen dataclass mutation test:**
```python
def test_frozen(self):
    b = Bar(...)
    with pytest.raises((dataclasses.FrozenInstanceError, TypeError, AttributeError)):
        b.close = 999.0  # type: ignore[misc]
```
Accept multiple exception types because Python version affects which is raised.

**DataFrame equality:**
```python
pd.testing.assert_frame_equal(df1, df2)
```

**Invariant tests:**
```python
def test_high_gte_open(self):
    assert (self.df["high"] >= self.df["open"]).all()
```
Use pandas boolean array `.all()` rather than iterating rows.

**Error message matching:**
```python
with pytest.raises(RuntimeError, match="max retries exceeded"):
    provider.get_bars(...)
```
Always pass `match=` to `pytest.raises` when testing error messages.

**Determinism verification:**
```python
def test_same_seed_same_data(self):
    df1 = SIM.get_bars("NVDA", ...)
    df2 = MarketSimulator(seed=42).get_bars("NVDA", ...)
    pd.testing.assert_frame_equal(df1, df2)

def test_different_seed_different_data(self):
    df1 = SIM.get_bars("AAPL", ...)
    df2 = MarketSimulator(seed=99).get_bars("AAPL", ...)
    assert not df1["close"].equals(df2["close"])
```

**Async testing:**
- `pytest-asyncio` is installed but no async tests exist yet
- Use `@pytest.mark.asyncio` when testing async FastAPI routes

---

*Testing analysis: 2026-06-25*
