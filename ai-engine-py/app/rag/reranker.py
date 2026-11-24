"""Rerank 客户端。

支持 DashScope gte-rerank 兼容形状，也兼容常见的
`{"results":[{"index":0,"relevance_score":0.9}]}` 返回。
未配置 RERANK_API_KEY/RERANK_BASE_URL 时，Retriever 会显式关闭精排并继续
使用 RRF 排名，而不是用伪分数冒充模型分数。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RerankError(RuntimeError):
    pass


class RerankNotConfigured(RerankError):
    pass


class DashScopeReranker:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.rerank_base_url.strip().rstrip("/")
        self.api_key = self.settings.rerank_api_key.get_secret_value()
        self.model = self.settings.rerank_model
        self.timeout = httpx.Timeout(self.settings.llm_timeout_seconds)

    @property
    def configured(self) -> bool:
        if not self.api_key or not self.base_url:
            return False
        parsed = urlparse(self.base_url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not self.configured:
            raise RerankNotConfigured("RERANK_BASE_URL / RERANK_API_KEY 未配置")
        if not documents:
            return []

        url = self.base_url
        if "rerank" not in url.lower():
            url = f"{url}/rerank"
        payload: dict[str, Any] = {
            "model": self.model,
            "input": {"query": query, "documents": list(documents)},
            "parameters": {"return_documents": False, "top_n": len(documents)},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise RerankError(f"Rerank 网络错误: {type(exc).__name__}") from exc

        if response.status_code >= 400:
            raise RerankError(self._error_detail(response))
        try:
            body = response.json()
        except ValueError as exc:
            raise RerankError("Rerank 返回非 JSON 响应") from exc

        results = self._extract_results(body)
        if len(results) != len(documents):
            raise RerankError(f"Rerank 返回数量不匹配: 期望 {len(documents)}，实际 {len(results)}")
        return results

    @staticmethod
    def _extract_results(body: dict[str, Any]) -> list[float]:
        raw_results = (
            (body.get("output") or {}).get("results")
            if isinstance(body.get("output"), dict)
            else None
        )
        if raw_results is None:
            raw_results = body.get("results")
        if raw_results is None:
            data = body.get("data")
            raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            raise RerankError("Rerank 响应缺少 results")

        scores = [0.0] * len(raw_results)
        for position, item in enumerate(raw_results):
            if not isinstance(item, dict):
                raise RerankError("Rerank results 元素不是对象")
            index = int(item.get("index", position))
            score = item.get("relevance_score", item.get("score"))
            if score is None:
                raise RerankError("Rerank result 缺少 relevance_score/score")
            values = [float(x) for x in scores]
            if index < 0 or index >= len(values):
                raise RerankError("Rerank 返回越界 index")
            values[index] = float(score)
            scores = values
        return scores

    def _error_detail(self, response: httpx.Response) -> str:
        text = response.text[:500]
        try:
            body = json.loads(text)
            message = (body.get("error") or {}).get("message") or body.get("message") or text
        except json.JSONDecodeError:
            message = text
        safe = str(message).replace(self.api_key, "***")[:300]
        return f"Rerank HTTP {response.status_code}: {safe}"
