#!/usr/bin/env python3
"""模型供应商连通性检查。

只发起最小请求并输出状态、模型、维度、耗时与 token 用量，
绝不打印 API Key 或完整响应内容。

用法（在 ai-engine-py 目录）:
    .\\.venv\\Scripts\\python.exe scripts\\check_models.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ENGINE_ROOT = Path(__file__).resolve().parents[1]
os.chdir(ENGINE_ROOT)
sys.path.insert(0, str(ENGINE_ROOT))

from app.core.config import Settings, get_settings  # noqa: E402


def redact(value: object, secrets: list[str]) -> str:
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:500]


def error_message(body: Any) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)
        if error:
            return str(error)
    return str(body)[:300]


async def check_llm(settings: Settings, client: httpx.AsyncClient) -> bool:
    api_key = settings.llm_api_key.get_secret_value()
    if not api_key:
        print("[skip] LLM_API_KEY 未配置")
        return False

    url = f"{settings.llm_base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {
        "model": settings.chat_model,
        "messages": [{"role": "user", "content": "连通性测试，请只回复 OK"}],
        "max_tokens": 16,
        "stream": False,
    }
    # DeepSeek 默认可能开启 thinking；测试只关心连通性，关闭以节省 token。
    if "deepseek.com" in settings.llm_base_url:
        payload["thinking"] = {"type": "disabled"}

    started = time.perf_counter()
    try:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        body = response.json()
        if response.status_code >= 400:
            print(
                f"[FAIL] LLM HTTP {response.status_code} "
                f"({latency_ms:.0f}ms): {redact(error_message(body), [api_key])}"
            )
            return False

        choices = body.get("choices") or []
        content = ""
        if choices:
            content = (choices[0].get("message") or {}).get("content") or ""
        usage = body.get("usage") or {}
        print(
            f"[OK] LLM model={body.get('model', settings.chat_model)} "
            f"latency={latency_ms:.0f}ms content_len={len(content)} "
            f"tokens={usage.get('total_tokens', '?')}"
        )
        return True
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        print(
            f"[FAIL] LLM ({latency_ms:.0f}ms): {redact(f'{type(exc).__name__}: {exc}', [api_key])}"
        )
        return False


async def check_embedding(settings: Settings, client: httpx.AsyncClient) -> bool:
    api_key = settings.embedding_api_key.get_secret_value()
    if not api_key:
        print("[skip] EMBEDDING_API_KEY 未配置")
        return False

    url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
    payload = {
        "model": settings.embedding_model,
        "input": ["连通性测试"],
    }
    started = time.perf_counter()
    try:
        response = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        body = response.json()
        if response.status_code >= 400:
            print(
                f"[FAIL] Embedding HTTP {response.status_code} "
                f"({latency_ms:.0f}ms): {redact(error_message(body), [api_key])}"
            )
            return False

        data = body.get("data") or []
        dimensions = len(data[0].get("embedding") or []) if data else 0
        usage = body.get("usage") or {}
        print(
            f"[OK] Embedding model={body.get('model', settings.embedding_model)} "
            f"latency={latency_ms:.0f}ms dimensions={dimensions} "
            f"tokens={usage.get('total_tokens', '?')}"
        )
        if dimensions != settings.embedding_dimensions:
            print(
                f"[WARN] 返回维度 {dimensions} 与契约 "
                f"{settings.embedding_dimensions} 不一致，写入 vector(1024) 会失败"
            )
            return False
        return True
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        print(
            f"[FAIL] Embedding ({latency_ms:.0f}ms): "
            f"{redact(f'{type(exc).__name__}: {exc}', [api_key])}"
        )
        return False


async def main() -> int:
    settings = get_settings()
    timeout = max(settings.llm_timeout_seconds, 30.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        llm_ok = await check_llm(settings, client)
        embedding_ok = await check_embedding(settings, client)

    print(f"[summary] llm={llm_ok} embedding={embedding_ok}")
    return 0 if llm_ok and embedding_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
