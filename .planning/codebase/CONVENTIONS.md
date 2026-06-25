# Coding Conventions

**Analysis Date:** 2026-06-25

## Naming Patterns

**Files:**
- Python source files: `snake_case.py` (e.g., `market_interface.py`, `simulator_provider.py`, `massive_provider.py`)
- Test files: `test_<module_name>.py` prefix (e.g., `test_market_interface.py`, `test_massive_provider.py`)
- Private/internal helpers: underscore-prefixed names at module level (e.g., `_KNOWN`, `_DEFAULTS`, `_DEFAULT_BASE`, `_RETRY_ON`, `_TickerParams`, `_params_for`)

**Classes:**
- PascalCase for all classes: `MarketDataProvider`, `MassiveProvider`, `SimulatorProvider`, `MarketSimulator`
- Private/internal dataclasses: underscore prefix PascalCase: `_TickerParams`
- Test classes: `TestFoo` / `TestFooBar` grouping by feature or scenario (e.g., `TestBar`, `TestGetBars`, `TestRetryLogic`)

**Functions and Methods:**
- `snake_case` for all functions and methods: `get_bars`, `get_latest_quote`, `create_provider`, `_fetch_aggs`, `_to_df`
- Private helpers: leading underscore: `_get`, `_fetch_aggs`, `_to_df`, `_get_snapshots`
- Factory functions: verb-noun: `create_provider()`

**Variables:**
- Module-level constants: `UPPER_SNAKE_CASE` (e.g., `_DEFAULT_BASE`, `_KNOWN`, `_RETRY_ON`, `_DEFAULTS`, `EXPECTED_COLS`, `SIM`, `PROVIDER`)
- Local variables: `snake_case`
- Type-hinted intermediate dicts: lowercase with type annotation (e.g., `results: dict[str, pd.DataFrame] = {}`)

**Type Annotations:**
- All public method signatures carry full type hints
- `from __future__ import annotations` used in every module for PEP 604 union syntax (`str | None`, `float | None`)
- Return types always annotated: `-> dict[str, pd.DataFrame]`, `-> dict[str, Quote]`, `-> None`
- Dataclass fields typed directly in the class body

## Code Style

**Formatting:**
- No dedicated formatter config detected (no `.prettierrc`, `pyproject.toml`, or `ruff.toml`)
- Consistent 4-space indentation throughout
- 79–100 character line width (PEP 8 style)
- Trailing commas in multi-line function calls and dict literals

**Linting:**
- No explicit linter config detected
- `# type: ignore[misc]` used sparingly in test files only (for frozen dataclass mutation tests)
- `# noqa` not used in production code

**Imports:**
- `from __future__ import annotations` is the first import in all service modules
- Standard library imports first, then third-party (pandas, numpy, requests), then local (`.market_interface`, `.market_simulator`)
- Relative imports used within the `data_ingestion` package (e.g., `from .market_interface import Bar`)
- Absolute imports in test files (e.g., `from app.services.data_ingestion.market_interface import Bar`)

## Import Organization

**Order (Python stdlib → third-party → local relative):**
1. `from __future__ import annotations`
2. Standard library: `abc`, `os`, `time`, `hashlib`, `dataclasses`, `datetime`
3. Third-party: `numpy`, `pandas`, `requests`
4. Local/relative: `from .market_interface import ...`, `from .market_simulator import ...`

**Path Aliases:**
- None — `sys.path` is patched in `conftest.py` to add `backend/` so tests use `app.*` imports

## Module-Level Structure Pattern

Each service module follows this order:
1. Module docstring (multi-line triple-quoted, explains purpose and design choices)
2. `from __future__ import annotations`
3. Standard library imports
4. Third-party imports
5. Local relative imports
6. Module-level constants (UPPER_SNAKE_CASE, prefixed with `_` if internal)
7. Helper dataclasses or functions (prefixed with `_`)
8. Main class(es)
9. Factory function (if any)

## Docstrings

**Module docstrings:** Always present, multi-line, triple-quoted. Explain:
- What the module does
- How provider selection works (for interface/factory modules)
- Which env vars drive behavior
- Key design guarantees

**Class docstrings:** Single-line for simple wrapper classes, multi-line for ABCs. Example:
```python
class MarketDataProvider(abc.ABC):
    """Abstract base — never instantiate directly; use create_provider()."""
```

**Method docstrings:** Present on abstract methods. Describe return schema, column names, sorting, adjustments. Omitted on simple delegation methods.

**Inline comments:** Used to explain non-obvious logic — GBM math, timestamp conversion steps, fallback behavior.

## Error Handling

**Strategy:** Raise `RuntimeError` with descriptive messages for API-level failures. Let exceptions propagate naturally from stdlib/third-party (e.g., `requests.raise_for_status()`).

**Patterns:**
- API 429/5xx: exponential backoff loop in `MassiveProvider._get()`, raises `RuntimeError("Massive API rate limit: max retries exceeded")` after 5 attempts
- API body error: `raise RuntimeError(f"Massive API error: {body.get('error', 'unknown')}")`
- Missing required env var: let `os.environ[key]` raise `KeyError` naturally — no custom wrapping
- Empty/inverted date ranges: return empty DataFrame with correct columns (no exception)
- Unknown ticker fallback: return synthetic GBM data (no exception)

**Not used:**
- Custom exception classes (not defined anywhere in the current codebase)
- Logging via the `logging` module — no logger calls found in production code

## Abstract Base Classes

**Pattern:** Use `abc.ABC` + `@abc.abstractmethod` for interfaces. All callers import only the ABC and the factory:
```python
# market_interface.py
class MarketDataProvider(abc.ABC):
    @abc.abstractmethod
    def get_bars(self, ...) -> dict[str, pd.DataFrame]: ...
```
Concrete implementations (`MassiveProvider`, `SimulatorProvider`) never imported directly by business logic — always obtained via `create_provider()`.

## Dataclasses

**Pattern:** Use `@dataclass(frozen=True)` for value objects representing domain entities:
```python
@dataclass(frozen=True)
class Bar:
    ticker: str
    date: date
    open: float
    ...
    vwap: float | None
```
- Frozen makes them hashable and immutable
- Field comments used for non-obvious semantics (e.g., `# trading date (ET)`)

## Configuration / Environment

**Pattern:** Read env vars at instantiation time with `os.environ.get()` (optional) or `os.environ[key]` (required):
```python
self._key = api_key or os.environ["MASSIVE_API_KEY"]
self._base = os.environ.get("MASSIVE_BASE_URL", _DEFAULT_BASE)
```
- Required vars: let `KeyError` propagate
- Optional vars: provide sensible defaults inline
- Never read env vars at module import time (deferred to constructor)

## Section Separators

**Pattern:** Section separators used in both source and test files for visual grouping:
```python
# ---------------------------------------------------------------------------
# Section Name
# ---------------------------------------------------------------------------
```
This 75-dash line style is consistent across all files.

## Paper-Trading Safety

Per `CLAUDE.md`: Assert at startup that Alpaca base URL is the paper endpoint. This is a hard constraint, not yet implemented in the current codebase (only market data is built). All future trading code must include this guard.

---

*Convention analysis: 2026-06-25*
