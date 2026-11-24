"""内部非流式检索接口。"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.deps import get_retriever
from app.api.guards import check_contract_version, check_workspace_header
from app.contract import validate_instance
from app.rag.retriever import HybridRetriever, RetrievalError
from app.schemas.requests import RetrievalSearchRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["retrieval"])


@router.post("/retrieval/search", summary="混合检索（非流式，供调试/透视）")
async def search(
    body: RetrievalSearchRequest,
    retriever: Annotated[HybridRetriever, Depends(get_retriever)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
    x_contract_version: Annotated[str | None, Header(alias="X-Contract-Version")] = None,
) -> dict:
    check_workspace_header(x_workspace_id, body.workspace_id)
    check_contract_version(x_contract_version)
    validate_instance(
        body.model_dump(mode="json", exclude_none=True),
        "RetrievalSearchRequest",
    )

    try:
        result = await retriever.retrieve(
            workspace_id=body.workspace_id,
            kb_ids=list(body.kb_ids),
            query=body.query,
            config=body.retrieval,
        )
    except RetrievalError as exc:
        logger.warning("检索失败: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "retrieval_failed",
                "message": str(exc)[:500],
                "retryable": True,
                "stage": "agent",
            },
        ) from exc

    response = {
        "trace_id": result.trace_id,
        "diagnostics": result.diagnostics,
    }
    validate_instance(response, "RetrievalSearchResponse")
    return response
