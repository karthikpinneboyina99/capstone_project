from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Find .env — check current dir first, then parent (project root when running from backend/)
_env_file = ".env" if Path(".env").exists() else str(Path(__file__).parent.parent.parent.parent / ".env")


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/trading_workstation"

    # Alpaca (paper trading only)
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"

    # Cerebras / LLM
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.cerebras.ai/v1"
    LLM_MODEL: str = "gpt-oss-120b"

    # Massive / Polygon market data (leave blank to use SimulatorProvider)
    MASSIVE_API_KEY: str = ""
    MASSIVE_BASE_URL: str = "https://api.polygon.io"

    # News
    NEWS_API_KEY: str = ""

    # App
    ENVIRONMENT: str = "development"
    TRADING_MODE: str = "paper"

    # Risk management defaults (all overridable via .env)
    MAX_POSITION_PCT: float = 0.10
    MAX_POSITIONS: int = 8
    DAILY_LOSS_LIMIT_PCT: float = 0.03

    # LLM prompt versioning — increment manually whenever the prompt template changes
    PROMPT_VERSION: int = 1

    # Default watchlist
    WATCHLIST: list[str] = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
        "META", "TSLA", "SPY", "QQQ", "JPM",
    ]

    model_config = SettingsConfigDict(env_file=_env_file, extra="ignore")


settings = Settings()
