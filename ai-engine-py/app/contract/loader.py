"""JSON Schema 加载器。

设计目标：Python 侧不维护第二份手写模型作为“契约事实”，
而是在运行时按需加载 docs/contracts/ai-engine-internal-v1.schema.json
校验请求/事件，确保网关、引擎、前端三端共享同一份定义。
"""

from __future__ import annotations

import json
import os
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator, FormatChecker

CONTRACT_VERSION: Final[str] = "1.0.0"
_SCHEMA_FILENAME: Final[str] = "ai-engine-internal-v1.schema.json"


class ContractViolation(ValueError):
    """消息体不符合契约时抛出，由 API 层转换为 422 ErrorResponse。"""

    def __init__(self, definition: str, message: str) -> None:
        super().__init__(f"{definition}: {message}")
        self.definition = definition
        self.message = message


def schema_path() -> Path:
    override = os.getenv("CONTRACT_SCHEMA_PATH")
    if override:
        path = Path(override).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"CONTRACT_SCHEMA_PATH 指向的文件不存在: {path}")

    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "docs" / "contracts" / _SCHEMA_FILENAME,
        Path.cwd().parent / "docs" / "contracts" / _SCHEMA_FILENAME,
        Path.cwd() / "docs" / "contracts" / _SCHEMA_FILENAME,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "找不到内部接口契约文件，请设置 CONTRACT_SCHEMA_PATH；已尝试: "
        + ", ".join(str(path) for path in candidates)
    )


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    raw = json.loads(schema_path().read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(raw)
    return raw


@cache
def _validator(definition: str) -> Draft202012Validator:
    schema = _schema()
    definitions = schema.get("$defs", {})
    if definition not in definitions:
        raise KeyError(f"契约中不存在 $defs/{definition}")

    # 组合一个只引用目标定义的子 Schema，避免每次校验都跑根 oneOf。
    sub_schema = {
        "$schema": schema["$schema"],
        "$id": schema["$id"],
        "$defs": definitions,
        "$ref": f"#/$defs/{definition}",
    }
    return Draft202012Validator(sub_schema, format_checker=FormatChecker())


@lru_cache(maxsize=1)
def contract_version() -> str:
    return str(_schema().get("x-contract-version", CONTRACT_VERSION))


def validate_instance(instance: Any, definition: str) -> None:
    """校验单条消息；失败时抛出带路径信息的 ContractViolation。"""
    errors = sorted(
        _validator(definition).iter_errors(instance),
        key=lambda error: list(error.absolute_path),
    )
    if not errors:
        return

    first = errors[0]
    location = "/".join(str(part) for part in first.absolute_path) or "<root>"
    raise ContractViolation(definition, f"/{location}: {first.message}")
