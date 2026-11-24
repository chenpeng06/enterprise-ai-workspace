"""Query 改写：失败时降级为原始 Query，不阻断检索。"""

from __future__ import annotations

import logging
import time

from app.services.llm import LLMError, OpenAICompatibleChatClient

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是企业研发知识库的检索查询改写器。
将用户问题改写为适合向量检索和关键词检索的简短查询：
- 保留专有名词、服务名、错误码、版本号；
- 补充同义关键词，不要回答问题；
- 只输出一行改写后的查询，不要解释，不要加引号。"""


class QueryRewriter:
    def __init__(self, client: OpenAICompatibleChatClient) -> None:
        self.client = client

    @property
    def configured(self) -> bool:
        return self.client.configured

    async def rewrite(self, query: str) -> tuple[str, str | None, float, dict[str, object] | None]:
        """返回 (rewritten, model, latency_ms, usage)。失败时返回原 Query。"""
        if not self.configured:
            return query, None, 0.0, None

        started = time.perf_counter()
        try:
            text, usage = await self.client.chat_text(
                [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": query},
                ],
                max_tokens=160,
                temperature=0.0,
            )
            rewritten = text.strip().strip('"').strip("'").splitlines()[0].strip()
            latency_ms = (time.perf_counter() - started) * 1000
            if not rewritten or len(rewritten) > 1000:
                return query, None, latency_ms, usage
            return rewritten, self.client.model, latency_ms, usage
        except LLMError as exc:
            latency_ms = (time.perf_counter() - started) * 1000
            logger.warning("Query 改写失败，回退原始 Query: %s", exc)
            return query, None, latency_ms, None
