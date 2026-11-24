"""内部 PDF 摄取接口（契约 v1.0.0）。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.contract import validate_instance
from app.core.config import get_settings
from app.services.ingest import IngestError, IngestService, get_task_status

router = APIRouter(tags=["ingest"])


@router.post("/ingest/tasks", status_code=status.HTTP_202_ACCEPTED)
async def create_ingest_task(body: dict[str, Any]) -> dict[str, Any]:
    validate_instance(body, "IngestCreateRequest")
    settings = get_settings()
    source = body["document"]["source"]
    if source["type"] != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": "当前本地部署仅支持 local PDF 源",
                "retryable": False,
                "stage": "ingest",
            },
        )
    root, path = await asyncio.to_thread(
        lambda: (
            Path(settings.ingest_local_root).resolve(),
            Path(source["uri"]).resolve(),
        )
    )
    if not path.is_relative_to(root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": "PDF 路径不在允许的上传目录内",
                "retryable": False,
                "stage": "ingest",
            },
        )
    file_exists = await asyncio.to_thread(path.exists)
    if not file_exists or path.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": "PDF 文件不存在或扩展名不合法",
                "retryable": False,
                "stage": "ingest",
            },
        )

    service = IngestService(settings)
    try:
        response = await service.create(body, path)
    except IngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "conflict",
                "message": str(exc),
                "retryable": False,
                "stage": "ingest",
            },
        ) from exc
    validate_instance(response, "IngestCreateResponse")
    return response


@router.get("/ingest/tasks/{task_id}")
async def ingest_task_status(task_id: UUID) -> dict[str, Any]:
    response = await get_task_status(get_settings(), task_id)
    if response is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "not_found",
                "message": "摄取任务不存在",
                "retryable": False,
                "stage": "ingest",
            },
        )
    validate_instance(response, "IngestTaskStatus")
    return response
