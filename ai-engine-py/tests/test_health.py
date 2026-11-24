"""健康探针与内部鉴权的冒烟测试。

PostgreSQL 不可用时 /health 返回 503，这是 Phase 1 无依赖启动的预期行为；
测试同时约束响应结构与契约版本，防止网关 readiness 解析漂移。
"""

from fastapi.testclient import TestClient

from app.main import app

INTERNAL_TOKEN = "dev-internal-token-change-me"


def test_health_rejects_missing_token() -> None:
    with TestClient(app) as client:
        response = client.get("/internal/v1/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_matches_contract_shape() -> None:
    with TestClient(app) as client:
        response = client.get(
            "/internal/v1/health",
            headers={"X-Internal-Token": INTERNAL_TOKEN},
        )

    assert response.status_code in (200, 503)
    body = response.json()
    assert body["service"] == "ai-engine-py"
    assert body["contract_version"] == "1.0.0"
    assert {"postgres", "llm", "embedding"} <= body["checks"].keys()
    assert body["status"] in ("ok", "degraded", "down")
