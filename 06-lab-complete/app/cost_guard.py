"""
Cost guard (tiêu chí 8) — Theo dõi và giới hạn chi phí LLM trên Redis.

- Cộng dồn chi phí theo token vào Redis (theo ngày và theo tháng).
- Tổng chi phí vượt DAILY_BUDGET_USD hoặc MONTHLY_BUDGET_USD → HTTP 402.
"""
import logging
from datetime import datetime, timezone

from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

logger = logging.getLogger("agent")

# Giá USD / 1K tokens (tham khảo gpt-4o-mini)
PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

_DAILY_TTL_SECONDS = 2 * 24 * 3600
_MONTHLY_TTL_SECONDS = 32 * 24 * 3600

_fallback_costs: dict[str, float] = {}


def _keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def _get_cost(redis_key: str) -> float:
    if r is not None:
        try:
            val = r.get(redis_key)
            return float(val) if val is not None else 0.0
        except Exception as exc:
            logger.warning("Redis unavailable in cost guard get, using fallback: %s", exc)
    return _fallback_costs.get(redis_key, 0.0)


def _add_cost(redis_key: str, delta: float, ttl_seconds: int) -> float:
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incrbyfloat(redis_key, delta)
            pipe.expire(redis_key, ttl_seconds)
            new_total, _ = pipe.execute()
            return float(new_total)
        except Exception as exc:
            logger.warning("Redis unavailable in cost guard incr, using fallback: %s", exc)
    _fallback_costs[redis_key] = _fallback_costs.get(redis_key, 0.0) + delta
    return _fallback_costs[redis_key]


def check_budget() -> None:
    """Gọi TRƯỚC khi gọi LLM. Hết budget → raise HTTPException(status_code=402)."""
    daily_key, monthly_key = _keys()
    daily_spent = _get_cost(daily_key)
    monthly_spent = _get_cost(monthly_key)

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily_spent, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )

    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly_spent, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Gọi SAU khi gọi LLM. Cộng chi phí của request vào tổng, trả về chi phí request."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _keys()
    _add_cost(daily_key, cost, _DAILY_TTL_SECONDS)
    _add_cost(monthly_key, cost, _MONTHLY_TTL_SECONDS)
    return round(cost, 6)
