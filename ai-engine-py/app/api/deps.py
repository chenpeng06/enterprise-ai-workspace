import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.agents.ops_assistant import OpsAssistant
from app.core.config import Settings, get_settings
from app.rag.retriever import HybridRetriever


async def require_internal_token(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    """内部接口守卫：仅允许持有共享密钥的 gateway-go 调用。"""
    expected = settings.internal_token.get_secret_value()
    provided = x_internal_token or ""
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "unauthorized",
                "message": "内部调用鉴权失败：X-Internal-Token 缺失或无效",
                "retryable": False,
                "stage": None,
            },
        )


def get_retriever() -> HybridRetriever:
    """请求级检索器；测试可通过 FastAPI dependency_overrides 替换。"""
    return HybridRetriever()


def get_ops_assistant() -> OpsAssistant:
    return OpsAssistant()
