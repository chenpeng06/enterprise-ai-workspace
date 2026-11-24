"""API 请求守卫：内部请求头一致性校验。"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status


def check_workspace_header(header_value: str | None, expected_workspace_id: UUID) -> None:
    """契约要求网关注入 X-Workspace-Id；直连调试时允许缺省，但存在即必须一致。"""
    if header_value is None or not header_value.strip():
        return
    try:
        actual = UUID(header_value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": "X-Workspace-Id 不是合法 UUID",
                "retryable": False,
                "stage": None,
            },
        ) from exc
    if actual != expected_workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "workspace_mismatch",
                "message": "X-Workspace-Id 与请求体 workspace_id 不一致",
                "retryable": False,
                "stage": None,
            },
        )


def check_contract_version(header_value: str | None) -> None:
    if header_value is None or not header_value.strip():
        return
    version = header_value.strip()
    if not version.startswith("1."):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": f"不支持的契约版本: {version}",
                "retryable": False,
                "stage": None,
            },
        )


def parse_trace_id(header_value: str | None) -> UUID | None:
    if header_value is None or not header_value.strip():
        return None
    try:
        return UUID(header_value.strip())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_request",
                "message": "X-Trace-Id 不是合法 UUID",
                "retryable": False,
                "stage": None,
            },
        ) from exc
