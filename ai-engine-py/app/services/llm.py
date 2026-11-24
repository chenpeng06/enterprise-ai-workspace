"""OpenAI 兼容的对话模型客户端（DeepSeek / 百炼 / 其他兼容端点）。"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    """模型调用失败（网络、鉴权、协议、空响应等）。"""


class LLMNotConfigured(LLMError):
    pass


@dataclass(slots=True)
class StreamDelta:
    content: str = ""
    reasoning: str | None = None
    usage: dict[str, Any] | None = None


class OpenAICompatibleChatClient:
    """最小 OpenAI Chat Completions 客户端。

    - 支持流式与非流式调用；
    - 对 DeepSeek 默认关闭 thinking，保证 Agent 工具/JSON 输出稳定；
    - 不记录 API Key 或完整响应正文。
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = self.settings.llm_base_url.rstrip("/")
        self.api_key = self.settings.llm_api_key.get_secret_value()
        self.model = self.settings.chat_model
        self.timeout = httpx.Timeout(self.settings.llm_timeout_seconds)

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise LLMNotConfigured("LLM_API_KEY 未配置")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": stream,
        }
        # DeepSeek 默认可能开启 thinking；工具/JSON 场景关闭更可控。
        if "deepseek.com" in self.base_url:
            payload["thinking"] = {"type": "disabled"}
        return payload

    async def chat_text(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> tuple[str, dict[str, Any]]:
        headers = self._headers()
        payload = self._payload(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 网络错误: {type(exc).__name__}") from exc

        body = self._parse_json_response(response)
        choices = body.get("choices") or []
        if not choices:
            raise LLMError("LLM 返回缺少 choices")
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回空内容")
        return content.strip(), self._normalize_usage(body)

    async def chat_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        text, usage = await self.chat_text(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        parsed = self._extract_json(text)
        return parsed, usage

    async def stream_chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> AsyncIterator[StreamDelta]:
        headers = self._headers()
        payload = self._payload(
            messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        raw = await response.aread()
                        raise LLMError(self._error_detail(response.status_code, raw))
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        usage = self._normalize_usage(chunk) if chunk.get("usage") else None
                        choices = chunk.get("choices") or []
                        if not choices:
                            if usage:
                                yield StreamDelta(usage=usage)
                            continue
                        delta = choices[0].get("delta") or {}
                        content = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content")
                        if content or reasoning or usage:
                            yield StreamDelta(
                                content=content,
                                reasoning=reasoning,
                                usage=usage,
                            )
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM 流式网络错误: {type(exc).__name__}") from exc

    def _parse_json_response(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise LLMError(self._error_detail(response.status_code, response.content))
        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("LLM 返回非 JSON 响应") from exc
        if not isinstance(body, dict):
            raise LLMError("LLM 响应不是 JSON 对象")
        return body

    def _error_detail(self, status_code: int, raw: bytes | str) -> str:
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        try:
            body = json.loads(text)
            message = (body.get("error") or {}).get("message") or body.get("message") or text
        except json.JSONDecodeError:
            message = text
        # 避免任何意外回显：只保留前 300 字符，并脱敏 Key。
        safe = str(message).replace(self.api_key, "***")[:300]
        return f"LLM HTTP {status_code}: {safe}"

    @staticmethod
    def _normalize_usage(body: dict[str, Any]) -> dict[str, Any]:
        usage = body.get("usage") or {}
        return {
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": int(usage.get("total_tokens") or 0),
            "model": str(body.get("model") or ""),
        }

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        candidates: list[str] = []
        fence = _JSON_FENCE.search(text)
        if fence:
            candidates.append(fence.group(1).strip())
        candidates.append(text.strip())
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            candidates.append(text[start : end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise LLMError("LLM 未返回合法 JSON")
