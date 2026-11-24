"""Embedding 客户端（OpenAI 兼容 /embeddings）。

当前默认供应商为阿里云百炼 text-embedding-v3（1024 维）。
DeepSeek 官方不提供 Embedding，因此使用独立的 EMBEDDING_API_KEY。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class EmbeddingNotConfigured(EmbeddingError):
    pass


class OpenAICompatibleEmbeddingClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.embedding_base_url.rstrip("/")
        self.api_key = self.settings.embedding_api_key.get_secret_value()
        self.model = self.settings.embedding_model
        self.dimensions = self.settings.embedding_dimensions
        self.timeout = httpx.Timeout(self.settings.llm_timeout_seconds)
        self.batch_size = 10

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        if not self.configured:
            raise EmbeddingNotConfigured("EMBEDDING_API_KEY 未配置")
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self.model, "input": texts}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error = "unknown"
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.post(
                        f"{self.base_url}/embeddings",
                        headers=headers,
                        json=payload,
                    )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    last_error = f"HTTP {response.status_code}"
                    await asyncio.sleep(2**attempt)
                    continue
                if response.status_code >= 400:
                    raise EmbeddingError(self._error_detail(response))
                body = response.json()
                data = body.get("data") or []
                if len(data) != len(texts):
                    raise EmbeddingError(
                        f"Embedding 返回数量不匹配: 期望 {len(texts)}，实际 {len(data)}"
                    )
                ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
                vectors = [list(map(float, item.get("embedding") or [])) for item in ordered]
                for vector in vectors:
                    if len(vector) != self.dimensions:
                        raise EmbeddingError(
                            f"Embedding 维度不匹配: 期望 {self.dimensions}，实际 {len(vector)}"
                        )
                return vectors
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"{type(exc).__name__}"
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                    continue
                raise EmbeddingError(f"Embedding 调用失败: {last_error}") from exc
        raise EmbeddingError(f"Embedding 调用失败: {last_error}")

    def _error_detail(self, response: httpx.Response) -> str:
        text = response.text[:500]
        try:
            body = json.loads(text)
            message = (body.get("error") or {}).get("message") or body.get("message") or text
        except json.JSONDecodeError:
            message = text
        safe = str(message).replace(self.api_key, "***")[:300]
        return f"Embedding HTTP {response.status_code}: {safe}"
