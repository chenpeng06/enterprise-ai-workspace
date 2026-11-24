#!/usr/bin/env python3
"""校验内部接口契约：JSON Schema 自检 + 全部示例消息（含根 oneOf 唯一性）。

用法:
    python scripts/validate_contracts.py

依赖: jsonschema>=4.20
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "contracts" / "ai-engine-internal-v1.schema.json"
EXAMPLES_DIR = ROOT / "docs" / "contracts" / "examples"

EXAMPLE_TO_DEF: dict[str, str] = {
    "chat-stream-request.json": "ChatStreamRequest",
    "meta-event.json": "MetaEvent",
    "thinking-event.json": "ThinkingEvent",
    "tool-calling-event.json": "ToolCallingEvent",
    "reranking-event.json": "RerankingEvent",
    "retrieval-event.json": "RetrievalEvent",
    "generating-event.json": "GeneratingEvent",
    "citation-event.json": "CitationEvent",
    "usage-event.json": "UsageEvent",
    "done-event.json": "DoneEvent",
    "error-response.json": "ErrorResponse",
    "health-response.json": "HealthResponse",
    "ingest-create-request.json": "IngestCreateRequest",
    "ingest-task-status.json": "IngestTaskStatus",
    "retrieval-search-request.json": "RetrievalSearchRequest",
}


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 中存在重复键: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    if not SCHEMA_PATH.exists():
        fail(f"契约文件不存在: {SCHEMA_PATH}")

    schema = load_json(SCHEMA_PATH)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001 - 契约校验脚本需要打印原始原因
        fail(f"Schema 自检失败: {exc}")

    defs = schema.get("$defs", {})
    print(f"[OK] Schema 通过 Draft 2020-12 校验，$defs={len(defs)}，oneOf={len(schema.get('oneOf', []))}")

    checker = FormatChecker()
    root_validator = Draft202012Validator(schema, format_checker=checker)

    missing = sorted(set(EXAMPLE_TO_DEF) - {p.name for p in EXAMPLES_DIR.glob("*.json")})
    if missing:
        fail(f"缺少示例文件: {', '.join(missing)}")

    failures = 0
    for filename, def_name in EXAMPLE_TO_DEF.items():
        path = EXAMPLES_DIR / filename
        instance = load_json(path)

        if def_name not in defs:
            fail(f"{filename}: 未定义的 $defs/{def_name}")
            continue

        sub_schema = {
            "$schema": schema["$schema"],
            "$id": schema["$id"],
            "$defs": defs,
            "$ref": f"#/$defs/{def_name}",
        }
        errors = sorted(
            Draft202012Validator(sub_schema, format_checker=checker).iter_errors(instance),
            key=lambda e: list(e.absolute_path),
        )
        if errors:
            failures += 1
            print(f"[FAIL] {filename} -> {def_name}", file=sys.stderr)
            for err in errors[:10]:
                location = "/".join(str(p) for p in err.absolute_path) or "<root>"
                print(f"       at {location}: {err.message}", file=sys.stderr)
            continue

        # 根 oneOf 必须唯一命中，防止请求/事件结构漂移后互相误判。
        root_errors = list(root_validator.iter_errors(instance))
        if root_errors:
            failures += 1
            print(f"[FAIL] {filename} 无法被根 oneOf 唯一匹配", file=sys.stderr)
            for err in root_errors[:5]:
                print(f"       {err.message}", file=sys.stderr)
            continue

        print(f"[OK] {filename} -> $defs/{def_name}")

    if failures:
        fail(f"{failures} 个示例未通过校验")

    print(f"[DONE] {len(EXAMPLE_TO_DEF)} 个示例全部通过契约校验")


if __name__ == "__main__":
    main()
