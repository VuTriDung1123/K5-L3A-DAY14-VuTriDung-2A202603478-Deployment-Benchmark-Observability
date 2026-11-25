"""
Production AI Agent — Part 6 Final Project

Tích hợp đầy đủ 12 tiêu chí production readiness:
- Config từ environment variables (12-Factor)
- Structured JSON logging
- Health check (GET /health) & Readiness check (GET /ready kiểm tra Redis)
- API Key authentication (X-API-Key → 401)
- Sliding-window Rate Limiting trên Redis (→ 429 + Retry-After)
- Cost Guard trên Redis (→ 402)
- Graceful shutdown qua FastAPI lifespan (không chặn handler SIGTERM của uvicorn)
"""
import asyncio
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import close_redis, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    """Định dạng mỗi dòng log của ứng dụng thành 1 JSON object hợp lệ."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lvl": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra_data = getattr(record, "extra_data", None)
        if isinstance(extra_data, dict):
            payload.update(extra_data)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _setup_logger() -> logging.Logger:
    app_logger = logging.getLogger("agent")
    app_logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    app_logger.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app_logger.addHandler(handler)
    app_logger.propagate = False
    return app_logger


logger = _setup_logger()

START_TIME = time.time()
_is_ready = False
_in_flight_requests = 0


def _log_event(level: int, msg: str, **fields) -> None:
    logger.log(level, msg, extra={"extra_data": fields})


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Quản lý vòng đời startup / graceful shutdown (phối hợp với SIGTERM của uvicorn)."""
    global _is_ready
    _is_ready = True
    _log_event(
        logging.INFO,
        "Agent started",
        event="startup",
        environment=settings.environment,
        port=settings.port,
        version=settings.app_version,
    )
    try:
        yield
    finally:
        _is_ready = False
        _log_event(
            logging.INFO,
            "Graceful shutdown initiated",
            event="shutdown_initiated",
            in_flight_requests=_in_flight_requests,
        )
        close_redis()
        _log_event(logging.INFO, "Shutdown complete", event="shutdown_complete")


app = FastAPI(
    title="Production AI Agent",
    version=settings.app_version,
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """Theo dõi in-flight requests và ghi structured JSON log cho từng HTTP request."""
    global _in_flight_requests
    _in_flight_requests += 1
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        _in_flight_requests -= 1
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        _log_event(
            logging.INFO,
            "http_request",
            event="request",
            method=request.method,
            path=request.url.path,
            status=status_code,
            ms=elapsed_ms,
        )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Không để lộ stack trace ra client khi gặp lỗi ngoài dự kiến."""
    _log_event(
        logging.ERROR,
        "Unhandled server error",
        event="error",
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = Field(default=None, max_length=128)


@app.get("/")
def root():
    return {
        "app": "Production AI Agent",
        "version": settings.app_version,
        "environment": settings.environment,
        "status": "running",
    }


@app.get("/health")
def health():
    """Liveness probe — luôn trả 200 khi process còn sống, kể cả khi Redis chưa sẵn sàng."""
    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "version": settings.app_version,
        "environment": settings.environment,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready")
def ready():
    """Readiness probe — trả 200 khi app và Redis sẵn sàng, 503 nếu chưa sẵn sàng."""
    if not _is_ready or not redis_healthy():
        raise HTTPException(
            status_code=503,
            detail="Service not ready: Redis unavailable or shutting down",
        )
    return {
        "ready": True,
        "redis": "connected",
        "in_flight_requests": _in_flight_requests,
    }


@app.post("/ask")
async def ask(
    body: AskRequest,
    api_key: str = Depends(verify_api_key),
):
    """Protected AI agent endpoint với Auth, Rate Limiting và Cost Guard."""
    rate_info = check_rate_limit(api_key)
    check_budget()

    answer = await asyncio.to_thread(llm_ask, body.question)

    input_tokens = max(4, len(body.question.split()) * 2)
    output_tokens = max(10, len(answer.split()) * 2)
    cost_usd = record_cost(input_tokens, output_tokens)

    _log_event(
        logging.INFO,
        "Agent answered question",
        event="agent_ask",
        user_id=body.user_id or "anonymous",
        question_length=len(body.question),
        answer_length=len(answer),
        cost_usd=cost_usd,
    )

    return {
        "question": body.question,
        "answer": answer,
        "cost_usd": cost_usd,
        "requests_remaining": rate_info["remaining"],
    }
