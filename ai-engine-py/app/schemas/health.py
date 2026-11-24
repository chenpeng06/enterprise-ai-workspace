from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "down"]
    latency_ms: float | None = None
    message: str | None = None


class HealthResponse(BaseModel):
    """与契约 $defs/HealthResponse 对齐的内部健康检查响应。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "down"]
    service: Literal["ai-engine-py"] = "ai-engine-py"
    version: str
    contract_version: str
    server_time: datetime
    uptime_seconds: float
    checks: dict[str, HealthCheck]
