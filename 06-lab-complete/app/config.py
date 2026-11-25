"""
Config — 12-Factor: mọi cấu hình đọc từ biến môi trường.
"""
import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Nạp .env nếu có ở local; biến môi trường thật của hệ thống/cloud luôn ưu tiên hơn
load_dotenv(override=False)


def _get_daily_budget() -> float:
    if "DAILY_BUDGET_USD" in os.environ:
        return float(os.environ["DAILY_BUDGET_USD"])
    if "MONTHLY_BUDGET_USD" in os.environ:
        return float(os.environ["MONTHLY_BUDGET_USD"])
    return 1.0


def _get_monthly_budget() -> float:
    if "MONTHLY_BUDGET_USD" in os.environ:
        return float(os.environ["MONTHLY_BUDGET_USD"])
    if "DAILY_BUDGET_USD" in os.environ:
        return float(os.environ["DAILY_BUDGET_USD"])
    return 10.0


@dataclass
class Settings:
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    app_version: str = field(default_factory=lambda: os.getenv("APP_VERSION", "1.0.0"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    rate_limit_per_minute: int = field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "10"))
    )
    daily_budget_usd: float = field(default_factory=_get_daily_budget)
    monthly_budget_usd: float = field(default_factory=_get_monthly_budget)


settings = Settings()
