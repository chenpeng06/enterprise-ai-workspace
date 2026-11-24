#!/usr/bin/env python3
"""把机器可读契约、DDL 与样例注入 docs/ARCHITECTURE.md。

用法:
    python scripts/sync_architecture.py           # 就地更新
    python scripts/sync_architecture.py --check   # CI 模式：过期则退出 1

注入区块由 <!-- BEGIN:<NAME> --> / <!-- END:<NAME> --> 标记包围；
源文件是唯一事实来源，禁止手工编辑注入后的内容。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "ARCHITECTURE.md"

INJECTIONS: dict[str, tuple[Path, str]] = {
    "CONTRACT_SCHEMA": (
        ROOT / "docs" / "contracts" / "ai-engine-internal-v1.schema.json",
        "json",
    ),
    "DDL": (ROOT / "deploy" / "initdb" / "01_schema.sql", "sql"),
    "RETRIEVAL_EXAMPLE": (
        ROOT / "docs" / "contracts" / "examples" / "retrieval-event.json",
        "json",
    ),
}


def fail(message: str) -> None:
    print(f"[FAIL] {message}", file=sys.stderr)
    raise SystemExit(1)


def read_source(source: Path, language: str) -> str:
    if not source.is_file():
        fail(f"注入源文件不存在: {source}")
    text = source.read_text(encoding="utf-8").strip("\n")
    if not text:
        fail(f"注入源文件为空: {source}")
    if language == "json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            fail(f"注入源不是合法 JSON: {source} ({exc})")
    return text + "\n"


def render_block(marker: str, source: Path, language: str) -> str:
    relative = source.relative_to(ROOT).as_posix()
    body = read_source(source, language)
    return (
        f"<!-- BEGIN:{marker} -->\n"
        f"<!-- 由 scripts/sync_architecture.py 从 {relative} 注入，请勿手工编辑。 -->\n"
        f"```{language}\n"
        f"{body}"
        f"```\n"
        f"<!-- END:{marker} -->"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="只检查是否存在过期注入，不写文件；过期时退出码为 1",
    )
    args = parser.parse_args()

    if not DOC_PATH.is_file():
        fail(f"找不到文档: {DOC_PATH}")

    document = DOC_PATH.read_text(encoding="utf-8")
    updated = document
    stale: list[str] = []

    for marker, (source, language) in INJECTIONS.items():
        pattern = re.compile(
            rf"<!-- BEGIN:{re.escape(marker)} -->.*?<!-- END:{re.escape(marker)} -->",
            re.DOTALL,
        )
        matches = pattern.findall(updated)
        if len(matches) != 1:
            fail(f"文档中 {marker} 标记数量应为 1，实际为 {len(matches)}")

        block = render_block(marker, source, language)
        new_document = pattern.sub(lambda _match: block, updated, count=1)
        if new_document != updated:
            stale.append(marker)
        updated = new_document

    if args.check:
        if stale:
            fail(f"ARCHITECTURE.md 注入区块已过期: {', '.join(stale)}；请运行同步脚本")
        print("[OK] ARCHITECTURE.md 注入区块与契约/DDL 源文件一致")
        return

    if not stale:
        print("[OK] ARCHITECTURE.md 已是最新，无需写入")
        return

    DOC_PATH.write_text(updated, encoding="utf-8", newline="\n")
    for marker in stale:
        source, _ = INJECTIONS[marker]
        print(f"[OK] 已注入 {marker} <- {source.relative_to(ROOT).as_posix()}")
    print(f"[DONE] 更新 {DOC_PATH.relative_to(ROOT).as_posix()}，共 {len(updated.splitlines())} 行")


if __name__ == "__main__":
    main()
