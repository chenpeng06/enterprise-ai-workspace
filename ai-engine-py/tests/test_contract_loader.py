"""契约加载器的回归测试：确保 Python 侧始终能读取仓库唯一事实来源。"""

import json

import pytest

from app.contract import (
    CONTRACT_VERSION,
    ContractViolation,
    contract_version,
    schema_path,
    validate_instance,
)


def test_schema_version_matches_constant() -> None:
    assert contract_version() == CONTRACT_VERSION


def test_chat_stream_example_passes_validation() -> None:
    example_path = schema_path().parent / "examples" / "chat-stream-request.json"
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    validate_instance(payload, "ChatStreamRequest")


def test_invalid_chat_stream_is_rejected() -> None:
    with pytest.raises(ContractViolation) as exc_info:
        validate_instance({"query": "缺少 workspace_id 等必填字段"}, "ChatStreamRequest")
    assert exc_info.value.definition == "ChatStreamRequest"
