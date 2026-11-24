"""SSE 流式问答接口。"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse

from app.agents.ops_assistant import OpsAssistant
from app.api.deps import get_ops_assistant
from app.api.guards import check_contract_version, check_workspace_header, parse_trace_id
from app.contract import validate_instance
from app.core.config import Settings, get_settings
from app.schemas.requests import ChatStreamRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

_HEARTBEAT_SECONDS = 15.0
_TERMINAL_EVENTS = {"done", "error"}


def _format_sse(event: str, data: dict[str, Any], event_id: int | None = None) -> str:
    lines = [f"event: {event}"]
    if event_id is not None:
        lines.append(f"id: {event_id}")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    lines.append(f"data: {payload}")
    return "\n".join(lines) + "\n\n"


def _error_data(
    trace_id: str,
    message_id: UUID,
    *,
    code: str = "internal_error",
    message: str = "流式生成异常终止",
    stage: str = "stream",
) -> dict[str, Any]:
    return {
        "message_id": str(message_id),
        "error": {
            "code": code,
            "message": message[:500],
            "retryable": False,
            "trace_id": trace_id,
            "stage": stage,
        },
    }


@router.post("/chat/stream", summary="数字员工流式问答（SSE）")
async def chat_stream(
    body: ChatStreamRequest,
    assistant: Annotated[OpsAssistant, Depends(get_ops_assistant)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    x_contract_version: Annotated[str | None, Header(alias="X-Contract-Version")] = None,
) -> StreamingResponse:
    check_workspace_header(x_workspace_id, body.workspace_id)
    check_contract_version(x_contract_version)
    validate_instance(
        body.model_dump(mode="json", exclude_none=True),
        "ChatStreamRequest",
    )

    trace_uuid = parse_trace_id(x_trace_id) or uuid4()
    trace_id = str(trace_uuid)
    meta = {
        "message_id": str(body.message_id),
        "conversation_id": str(body.conversation_id),
        "trace_id": trace_id,
        "workspace_id": str(body.workspace_id),
        "mode": body.mode,
        "agent_name": body.resolved_agent().name if body.mode == "agent" else None,
        "model": settings.chat_model,
        "contract_version": "1.0.0",
        "server_time": datetime.now(UTC).isoformat(timespec="milliseconds"),
    }
    validate_instance(meta, "MetaData")

    async def event_stream() -> AsyncGenerator[str, None]:
        sequence = 1
        yield _format_sse("meta", meta, sequence)
        iterator: AsyncIterator[dict[str, Any]] = assistant.stream_events(
            body,
            trace_id=trace_id,
        ).__aiter__()
        pending: asyncio.Task[dict[str, Any]] | None = None
        terminal = False

        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(anext(iterator))
                done, _ = await asyncio.wait({pending}, timeout=_HEARTBEAT_SECONDS)
                if not done:
                    yield ": ping\n\n"
                    continue

                try:
                    event = pending.result()
                except StopAsyncIteration:
                    pending = None
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.exception("SSE 事件生成异常")
                    sequence += 1
                    yield _format_sse(
                        "error",
                        _error_data(
                            trace_id,
                            body.message_id,
                            message=f"事件生成异常: {type(exc).__name__}",
                        ),
                        sequence,
                    )
                    terminal = True
                    break
                pending = None
                sequence += 1
                yield _format_sse(event["event"], event["data"], sequence)
                if event["event"] in _TERMINAL_EVENTS:
                    terminal = True
                    break

            if not terminal:
                sequence += 1
                yield _format_sse(
                    "error",
                    _error_data(
                        trace_id,
                        body.message_id,
                        message="事件流在发送终态事件前结束",
                    ),
                    sequence,
                )
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
            with suppress(Exception):
                await iterator.aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "X-Contract-Version": "1.0.0",
        },
    )
