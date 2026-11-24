import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response, status

from app.contract import contract_version
from app.core.config import Settings, get_settings
from app.db.session import ping_database
from app.schemas.health import HealthCheck, HealthResponse

router = APIRouter(tags=["internal"])

_STARTED_AT = time.monotonic()
_PROBE_TIMEOUT_SECONDS = 2.0


async def _probe_postgres(settings: Settings) -> str | None:
    await ping_database(settings)
    return None


async def _probe_llm(settings: Settings) -> str | None:
    if not settings.llm_api_key.get_secret_value():
        return "未配置 LLM_API_KEY（Phase 1 允许，Phase 2 必需）"
    # 仅做配置就绪检查；真实连通性由 scripts/check_models.py 验证。
    return None


async def _probe_embedding(settings: Settings) -> str | None:
    if not settings.embedding_api_key.get_secret_value():
        return "未配置 EMBEDDING_API_KEY（Embedding 需独立供应商，DeepSeek 官方不提供）"
    return None


async def _probe(
    name: str,
    check: Callable[[], Awaitable[str | None]],
) -> tuple[str, HealthCheck, bool]:
    started_at = time.perf_counter()
    try:
        message = await asyncio.wait_for(check(), timeout=_PROBE_TIMEOUT_SECONDS)
    except TimeoutError:
        latency_ms = (time.perf_counter() - started_at) * 1000
        return (
            name,
            HealthCheck(
                status="down",
                latency_ms=round(latency_ms, 2),
                message=f"探测超时（{_PROBE_TIMEOUT_SECONDS:g}s）",
            ),
            True,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - started_at) * 1000
        detail = str(exc).strip() or exc.__class__.__name__
        return (
            name,
            HealthCheck(status="down", latency_ms=round(latency_ms, 2), message=detail[:500]),
            True,
        )

    latency_ms = (time.perf_counter() - started_at) * 1000
    if message:
        return (
            name,
            HealthCheck(status="degraded", latency_ms=round(latency_ms, 2), message=message[:500]),
            False,
        )
    return name, HealthCheck(status="ok", latency_ms=round(latency_ms, 2)), False


@router.get("/health", response_model=HealthResponse, summary="内部健康检查")
async def health(
    response: Response,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    results = await asyncio.gather(
        _probe("postgres", lambda: _probe_postgres(settings)),
        _probe("llm", lambda: _probe_llm(settings)),
        _probe("embedding", lambda: _probe_embedding(settings)),
    )

    checks = {name: check for name, check, _ in results}
    has_down = any(is_down for _, _, is_down in results)
    has_degraded = any(check.status == "degraded" for _, check, _ in results)

    if has_down:
        overall = "down"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif has_degraded:
        overall = "degraded"
    else:
        overall = "ok"

    return HealthResponse(
        status=overall,
        version=settings.app_version,
        contract_version=contract_version(),
        server_time=datetime.now(UTC),
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
        checks=checks,
    )
