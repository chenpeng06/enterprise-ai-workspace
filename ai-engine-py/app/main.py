from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.contract import ContractViolation, contract_version
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger.info(
        "ai-engine 启动 env=%s version=%s contract=%s",
        settings.app_env,
        settings.app_version,
        contract_version(),
    )
    try:
        yield
    finally:
        await dispose_engine()
        logger.info("ai-engine 已停止")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            error = detail
        else:
            error = {
                "code": "not_found" if exc.status_code == 404 else "invalid_request",
                "message": str(detail),
                "retryable": False,
            }
        return JSONResponse(status_code=exc.status_code, content={"error": error})

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "请求体不符合内部接口契约",
                    "retryable": False,
                    "details": {"errors": jsonable_encoder(exc.errors())[:10]},
                }
            },
        )

    @app.exception_handler(ContractViolation)
    async def handle_contract_violation(_: Request, exc: ContractViolation) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": str(exc),
                    "retryable": False,
                    "details": {"definition": exc.definition},
                }
            },
        )


def create_app() -> FastAPI:
    settings = get_settings()
    is_production = settings.app_env == "production"

    app = FastAPI(
        title="Enterprise AI Workspace · AI Engine",
        version=settings.app_version,
        description="文档解析、混合检索、Rerank 与 LangGraph 数字员工内部服务",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    register_exception_handlers(app)
    return app


app = create_app()
