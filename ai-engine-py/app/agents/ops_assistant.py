"""企业研发运维数字员工（LangGraph）。

图结构：
    START ──(agent)──> Planner ──> RAG Retrieve ──> Tools ──> Reviewer ──> Writer
      └────(rag)───────────────────> RAG Retrieve ──> Reviewer ──> Writer

Writer 通过异步队列向外 yield 标准 SSE 业务事件；API 层负责追加 meta 与事件 id。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from app.core.config import Settings, get_settings
from app.rag.retriever import ChunkCandidate, HybridRetriever, RetrievalError, RetrievalResult
from app.schemas.requests import ChatStreamRequest
from app.services.llm import (
    LLMError,
    LLMNotConfigured,
    OpenAICompatibleChatClient,
)

logger = logging.getLogger(__name__)

_NODE_INDEX = {
    "planner": 0,
    "rag_retrieve": 1,
    "tools": 2,
    "reviewer": 3,
    "writer": 4,
}

_PLANNER_SYSTEM_PROMPT = """你是企业研发运维数字员工的任务规划器。
将用户问题拆解为 2-6 个可执行步骤，只输出 JSON，不要解释：
{"steps":[
  {"step_index":0,"action":"retrieve","description":"检索相关规范与证据"},
  {"step_index":1,"action":"tool","description":"分析服务日志","tool_name":"analyze_service_logs"},
  {"step_index":2,"action":"review","description":"核查证据"},
  {"step_index":3,"action":"answer","description":"生成带角标的结构化报告"}
]}
action 只能是 retrieve/tool/review/answer；tool 步骤必须给出 tool_name。"""

_WRITER_SYSTEM_PROMPT = """你是企业研发运维数字员工，负责输出可执行、可追溯的结构化报告。
硬性要求：
1. 只能依据【证据】和【工具结果】作答，不得编造规范、指标或结论；
2. 每个事实性结论必须带角标 [n]，n 对应证据编号；
3. 使用 Markdown，按“结论 / 处置步骤 / 依据”组织；
4. 如果证据不足，明确说明不确定，不要猜测；
5. 不要输出思考过程，只输出最终报告。"""


class AgentState(TypedDict, total=False):
    request: ChatStreamRequest
    plan: list[dict[str, Any]]
    retrieval: RetrievalResult
    tool_results: list[dict[str, Any]]
    review: dict[str, Any]
    citations: list[dict[str, Any]]
    steps: list[dict[str, Any]]
    answer: str


class OpsAssistant:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        retriever: Any | None = None,
        llm_client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.retriever = retriever or HybridRetriever(settings=self.settings)
        self.llm = llm_client or OpenAICompatibleChatClient(self.settings)
        self._graph = self._build_graph()
        self._queue: asyncio.Queue[dict[str, Any] | None] | None = None
        self._request: ChatStreamRequest | None = None
        self._trace_id: str | None = None
        self._run_started = 0.0
        self._first_token_at: float | None = None
        self._usage: dict[str, Any] = {}

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentState)
        builder.add_node("planner", self._planner_node)
        builder.add_node("rag_retrieve", self._rag_node)
        builder.add_node("tools", self._tools_node)
        builder.add_node("reviewer", self._reviewer_node)
        builder.add_node("writer", self._writer_node)

        builder.add_conditional_edges(
            START,
            self._route_start,
            {"agent": "planner", "rag": "rag_retrieve"},
        )
        builder.add_edge("planner", "rag_retrieve")
        builder.add_conditional_edges(
            "rag_retrieve",
            self._route_after_retrieval,
            {"tools": "tools", "reviewer": "reviewer"},
        )
        builder.add_edge("tools", "reviewer")
        builder.add_edge("reviewer", "writer")
        builder.add_edge("writer", END)
        return builder.compile()

    async def stream_events(
        self,
        request: ChatStreamRequest,
        *,
        trace_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self._request = request
        self._trace_id = trace_id or str(uuid4())
        self._run_started = time.perf_counter()
        self._first_token_at = None
        self._usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "model": self.settings.chat_model,
        }
        self._queue = asyncio.Queue()
        initial: AgentState = {
            "request": request,
            "plan": [],
            "tool_results": [],
            "steps": [],
            "citations": [],
        }
        task = asyncio.create_task(self._run_graph(initial))
        try:
            while True:
                item = await self._queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task

    async def _run_graph(self, initial: AgentState) -> None:
        try:
            await self._graph.ainvoke(initial)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("数字员工执行失败")
            await self._emit("error", self._error_data(exc))
        finally:
            if self._queue is not None:
                await self._queue.put(None)

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        if self._queue is None:
            raise RuntimeError("Agent 事件队列未初始化")
        await self._queue.put({"event": event, "data": data})

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    def _route_start(self, state: AgentState) -> str:
        return "agent" if state["request"].mode == "agent" else "rag"

    def _route_after_retrieval(self, state: AgentState) -> str:
        return "tools" if state["request"].mode == "agent" else "reviewer"

    async def _planner_node(self, state: AgentState) -> dict[str, Any]:
        request = state["request"]
        agent_cfg = request.resolved_agent()
        started = time.perf_counter()
        started_at = _iso_now()

        await self._emit(
            "thinking",
            {
                "node": "planner",
                "step_index": _NODE_INDEX["planner"],
                "step_id": "planner-1",
                "status": "started",
                "title": "任务拆解",
                "detail": "分析问题并生成执行计划。",
                "started_at": started_at,
                "latency_ms": None,
            },
        )

        if not agent_cfg.planner.enabled:
            plan = self._fallback_plan()
            latency_ms = (time.perf_counter() - started) * 1000
            await self._emit(
                "thinking",
                {
                    "node": "planner",
                    "step_index": _NODE_INDEX["planner"],
                    "step_id": "planner-1",
                    "status": "skipped",
                    "title": "任务拆解",
                    "detail": "Planner 已禁用，使用默认执行计划。",
                    "started_at": started_at,
                    "latency_ms": round(latency_ms, 2),
                    "plan": plan,
                },
            )
            return {
                "plan": plan,
                "steps": self._with_step(state, "planner", "skipped", "任务拆解", latency_ms),
            }

        status = "succeeded"
        detail = "已生成执行计划。"
        plan = self._fallback_plan()
        try:
            payload, usage = await self.llm.chat_json(
                [
                    {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
                    {"role": "user", "content": request.query},
                ],
                max_tokens=800,
                temperature=0.1,
            )
            self._record_usage(usage)
            plan = self._normalize_plan(payload, agent_cfg.planner.max_plan_steps)
        except Exception as exc:
            status = "failed"
            detail = f"Planner 调用失败，使用规则计划：{_safe_message(exc)}"
            logger.warning("Planner 失败: %s", exc)

        latency_ms = (time.perf_counter() - started) * 1000
        await self._emit(
            "thinking",
            {
                "node": "planner",
                "step_index": _NODE_INDEX["planner"],
                "step_id": "planner-1",
                "status": status,
                "title": "任务拆解",
                "detail": detail,
                "started_at": started_at,
                "latency_ms": round(latency_ms, 2),
                "plan": plan,
                "attributes": {"step_count": len(plan)},
            },
        )
        return {
            "plan": plan,
            "steps": self._with_step(state, "planner", status, "任务拆解", latency_ms),
        }

    async def _rag_node(self, state: AgentState) -> dict[str, Any]:
        request = state["request"]
        started = time.perf_counter()
        started_at = _iso_now()
        step_index = _NODE_INDEX["rag_retrieve"]
        await self._emit(
            "thinking",
            {
                "node": "rag_retrieve",
                "step_index": step_index,
                "step_id": "rag-1",
                "status": "started",
                "title": "混合检索与重排",
                "detail": "向量召回 + 全文 BM25 → RRF → Rerank。",
                "started_at": started_at,
                "latency_ms": None,
            },
        )

        call_id = f"call-{uuid4().hex[:10]}"
        await self._emit(
            "tool_calling",
            {
                "call_id": call_id,
                "node": "rag_retrieve",
                "tool_name": "search_knowledge_base",
                "arguments": {
                    "query": request.query,
                    "kb_ids": [str(item) for item in request.kb_ids],
                    "top_k": request.retrieval.top_k,
                },
                "status": "started",
                "result_summary": None,
                "result": None,
                "latency_ms": None,
                "error": None,
            },
        )

        rerank_configured = bool(
            request.retrieval.enable_rerank
            and getattr(self.retriever, "reranker", None) is not None
        )
        rerank_model = str(
            getattr(getattr(self.retriever, "reranker", None), "model", "")
            or request.retrieval.rerank_model
        )
        if rerank_configured:
            await self._emit(
                "reranking",
                {
                    "node": "rag_retrieve",
                    "status": "started",
                    "model": rerank_model,
                    "candidate_count": 0,
                    "top_n": request.retrieval.top_k,
                    "score_threshold": request.retrieval.min_rerank_score,
                    "passed_count": None,
                    "latency_ms": None,
                    "error": None,
                },
            )

        try:
            result = await self.retriever.retrieve(
                workspace_id=request.workspace_id,
                kb_ids=list(request.kb_ids),
                query=request.query,
                config=request.retrieval,
                trace_id=self._trace_id,
            )
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError(f"检索失败: {_safe_message(exc)}") from exc

        if result.rewrite_usage:
            self._record_usage(result.rewrite_usage)

        rerank_stats = result.diagnostics["stages"]["rerank"]
        if result.rerank_error:
            await self._emit(
                "reranking",
                {
                    "node": "rag_retrieve",
                    "status": "failed",
                    "model": rerank_model,
                    "candidate_count": rerank_stats["candidates"],
                    "top_n": request.retrieval.top_k,
                    "score_threshold": request.retrieval.min_rerank_score,
                    "passed_count": None,
                    "latency_ms": rerank_stats["latency_ms"],
                    "error": {
                        "code": "rerank_failed",
                        "message": result.rerank_error[:500],
                        "retryable": True,
                        "trace_id": self._trace_id,
                        "stage": "rerank",
                    },
                },
            )
        elif rerank_stats["enabled"]:
            await self._emit(
                "reranking",
                {
                    "node": "rag_retrieve",
                    "status": "succeeded",
                    "model": rerank_stats.get("model"),
                    "candidate_count": rerank_stats["candidates"],
                    "top_n": request.retrieval.top_k,
                    "score_threshold": rerank_stats.get("score_threshold"),
                    "passed_count": rerank_stats["passed"],
                    "latency_ms": rerank_stats["latency_ms"],
                    "error": None,
                },
            )
        else:
            await self._emit(
                "reranking",
                {
                    "node": "rag_retrieve",
                    "status": "skipped",
                    "model": None,
                    "candidate_count": rerank_stats["candidates"],
                    "top_n": request.retrieval.top_k,
                    "score_threshold": rerank_stats.get("score_threshold"),
                    "passed_count": 0,
                    "latency_ms": rerank_stats["latency_ms"],
                    "error": None,
                },
            )

        await self._emit(
            "tool_calling",
            {
                "call_id": call_id,
                "node": "rag_retrieve",
                "tool_name": "search_knowledge_base",
                "arguments": {"query": request.query},
                "status": "succeeded",
                "result_summary": (
                    f"检索候选 {len(result.diagnostics['candidates'])} 条，"
                    f"选中 {result.diagnostics['selected_count']} 条。"
                ),
                "result": {
                    "trace_id": result.trace_id,
                    "candidates": len(result.diagnostics["candidates"]),
                    "selected": result.diagnostics["selected_count"],
                    "rerank_enabled": result.diagnostics["stages"]["rerank"]["enabled"],
                },
                "latency_ms": result.total_ms,
                "error": None,
            },
        )

        retrieval_data = {
            "message_id": str(request.message_id),
            "diagnostics": result.diagnostics,
        }
        await self._emit("retrieval", retrieval_data)
        citations = [self._citation_payload(item) for item in result.selected]

        latency_ms = (time.perf_counter() - started) * 1000
        await self._emit(
            "thinking",
            {
                "node": "rag_retrieve",
                "step_index": step_index,
                "step_id": "rag-1",
                "status": "succeeded",
                "title": "混合检索与重排",
                "detail": f"选中 {len(result.selected)} 条证据。",
                "started_at": started_at,
                "latency_ms": round(latency_ms, 2),
                "attributes": {
                    "trace_id": result.trace_id,
                    "selected_count": len(result.selected),
                },
            },
        )
        return {
            "retrieval": result,
            "citations": citations,
            "steps": self._with_step(
                state,
                "rag_retrieve",
                "succeeded",
                "混合检索与重排",
                latency_ms,
                tool_name="search_knowledge_base",
            ),
        }

    async def _tools_node(self, state: AgentState) -> dict[str, Any]:
        request = state["request"]
        agent_cfg = request.resolved_agent()
        started = time.perf_counter()
        started_at = _iso_now()
        await self._emit(
            "thinking",
            {
                "node": "tools",
                "step_index": _NODE_INDEX["tools"],
                "step_id": "tools-1",
                "status": "started",
                "title": "工具调用",
                "detail": "执行日志分析与服务状态查询。",
                "started_at": started_at,
                "latency_ms": None,
            },
        )

        if not agent_cfg.enable_tools:
            await self._emit(
                "thinking",
                {
                    "node": "tools",
                    "step_index": _NODE_INDEX["tools"],
                    "step_id": "tools-1",
                    "status": "skipped",
                    "title": "工具调用",
                    "detail": "数字员工工具已禁用。",
                    "started_at": started_at,
                    "latency_ms": 0.0,
                },
            )
            return {
                "tool_results": [],
                "steps": self._with_step(state, "tools", "skipped", "工具调用", 0.0),
            }

        service = self._service_from_query(request.query)
        allowed = set(agent_cfg.allowed_tools)
        tool_results: list[dict[str, Any]] = []
        steps = list(state.get("steps", []))

        for tool_name in ("analyze_service_logs", "query_service_status"):
            if tool_name not in allowed:
                continue
            call_id = f"call-{uuid4().hex[:10]}"
            await self._emit(
                "tool_calling",
                {
                    "call_id": call_id,
                    "node": "tools",
                    "tool_name": tool_name,
                    "arguments": {
                        "service": service,
                        "window_minutes": 30 if tool_name == "analyze_service_logs" else None,
                    },
                    "status": "started",
                    "result_summary": None,
                    "result": None,
                    "latency_ms": None,
                    "error": None,
                },
            )
            tool_started = time.perf_counter()
            if tool_name == "analyze_service_logs":
                result = self._mock_log_analysis(service)
                summary = (
                    f"{service} 近 30 分钟错误率 "
                    f"{result['error_rate'] * 100:.1f}%（阈值 {result['threshold'] * 100:.0f}%）。"
                )
            else:
                result = self._mock_service_status(service)
                summary = f"{service} 当前状态：{result['status']}。"
            latency_ms = (time.perf_counter() - tool_started) * 1000
            tool_results.append({"tool_name": tool_name, "result": result})
            await self._emit(
                "tool_calling",
                {
                    "call_id": call_id,
                    "node": "tools",
                    "tool_name": tool_name,
                    "arguments": {"service": service, "window_minutes": 30}
                    if tool_name == "analyze_service_logs"
                    else {"service": service},
                    "status": "succeeded",
                    "result_summary": summary,
                    "result": result,
                    "latency_ms": round(latency_ms, 2),
                    "error": None,
                },
            )
            steps.append(
                self._step_payload("tools", "succeeded", f"调用 {tool_name}", latency_ms, tool_name)
            )

        latency_ms = (time.perf_counter() - started) * 1000
        await self._emit(
            "thinking",
            {
                "node": "tools",
                "step_index": _NODE_INDEX["tools"],
                "step_id": "tools-1",
                "status": "succeeded",
                "title": "工具调用",
                "detail": f"完成 {len(tool_results)} 个工具调用。",
                "started_at": started_at,
                "latency_ms": round(latency_ms, 2),
            },
        )
        if not tool_results:
            steps.append(self._step_payload("tools", "skipped", "工具调用", latency_ms, None))
        return {"tool_results": tool_results, "steps": steps}

    async def _reviewer_node(self, state: AgentState) -> dict[str, Any]:
        request = state["request"]
        cfg = request.resolved_agent().reviewer
        retrieval = state.get("retrieval")
        selected = retrieval.selected if retrieval else []
        started = time.perf_counter()
        started_at = _iso_now()

        top_score = 0.0
        if selected:
            top_score = float(
                selected[0].rerank_score
                if selected[0].rerank_score is not None
                else selected[0].vector_score or 0.0
            )

        if not selected:
            passed = False
            status = "failed"
            reason = "没有检索到可用证据，拒绝生成答案。"
        elif not cfg.enabled:
            passed = True
            status = "skipped"
            reason = "Reviewer 已禁用，仅做证据存在性检查。"
        elif top_score < cfg.min_context_score:
            passed = False
            status = "failed"
            reason = f"最高证据分 {top_score:.3f} 低于阈值 {cfg.min_context_score:.3f}，拒绝回答。"
        else:
            passed = True
            status = "succeeded"
            reason = "证据覆盖度满足阈值。"

        await self._emit(
            "thinking",
            {
                "node": "reviewer",
                "step_index": _NODE_INDEX["reviewer"],
                "step_id": "reviewer-1",
                "status": status,
                "title": "防幻觉核查",
                "detail": reason,
                "started_at": started_at,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "attributes": {
                    "passed": passed,
                    "top_score": round(top_score, 6),
                    "min_context_score": cfg.min_context_score,
                    "selected_count": len(selected),
                    "unsupported_claims": 0 if passed else 1,
                },
            },
        )
        review = {
            "passed": passed,
            "reason": reason,
            "top_score": top_score,
            "min_context_score": cfg.min_context_score,
            "refusal_message": cfg.refusal_message,
        }
        return {
            "review": review,
            "steps": self._with_step(
                state,
                "reviewer",
                status,
                "防幻觉核查",
                (time.perf_counter() - started) * 1000,
            ),
        }

    async def _writer_node(self, state: AgentState) -> dict[str, Any]:
        request = state["request"]
        retrieval = state.get("retrieval")
        citations = state.get("citations") or []
        review = state.get("review") or {"passed": False, "refusal_message": "证据不足"}
        started = time.perf_counter()
        started_at = _iso_now()
        await self._emit(
            "thinking",
            {
                "node": "writer",
                "step_index": _NODE_INDEX["writer"],
                "step_id": "writer-1",
                "status": "started",
                "title": "生成结构化报告",
                "detail": "基于证据生成带角标的报告。",
                "started_at": started_at,
                "latency_ms": None,
            },
        )

        passed = bool(review.get("passed"))
        answer = ""
        index = 0
        if passed:
            for citation in citations:
                await self._emit(
                    "citation",
                    {"message_id": str(request.message_id), "citation": citation},
                )

            messages = self._writer_messages(state)
            try:
                async for delta in self.llm.stream_chat(
                    messages,
                    max_tokens=request.generation.max_tokens,
                    temperature=request.generation.temperature,
                ):
                    if delta.usage:
                        self._record_usage(delta.usage)
                    if delta.content:
                        if self._first_token_at is None:
                            self._first_token_at = time.perf_counter()
                        answer += delta.content
                        await self._emit(
                            "generating",
                            {
                                "message_id": str(request.message_id),
                                "delta": delta.content,
                                "reasoning_delta": delta.reasoning,
                                "index": index,
                                "tokens_so_far": self._usage.get("completion_tokens", 0),
                            },
                        )
                        index += 1
            except (LLMError, LLMNotConfigured) as exc:
                raise LLMError(f"Writer 调用失败: {_safe_message(exc)}") from exc

            if not answer.strip():
                raise LLMError("Writer 未返回任何内容")
            finish_reason = "stop"
        else:
            refusal = str(review.get("refusal_message") or "当前没有足够可靠的依据回答该问题。")
            answer = refusal
            for chunk in _chunks(refusal, 60):
                if self._first_token_at is None:
                    self._first_token_at = time.perf_counter()
                await self._emit(
                    "generating",
                    {
                        "message_id": str(request.message_id),
                        "delta": chunk,
                        "reasoning_delta": None,
                        "index": index,
                        "tokens_so_far": max(1, len(answer) // 4),
                    },
                )
                index += 1
            finish_reason = "refused"
            citations = []

        generation_ms = (time.perf_counter() - started) * 1000
        steps = self._with_step(
            state,
            "writer",
            "succeeded",
            "生成结构化报告",
            generation_ms,
        )
        await self._emit(
            "thinking",
            {
                "node": "writer",
                "step_index": _NODE_INDEX["writer"],
                "step_id": "writer-1",
                "status": "succeeded",
                "title": "生成结构化报告",
                "detail": f"生成 {len(answer)} 字符，引用 {len(citations)} 条证据。",
                "started_at": started_at,
                "latency_ms": round(generation_ms, 2),
            },
        )

        usage = self._usage_event(request)
        await self._emit("usage", {"message_id": str(request.message_id), "usage": usage})

        timings = {
            "ttft_ms": round(
                ((self._first_token_at or time.perf_counter()) - self._run_started) * 1000,
                2,
            ),
            "retrieval_ms": round(retrieval.retrieval_ms if retrieval else 0.0, 2),
            "rerank_ms": round(retrieval.rerank_ms if retrieval else 0.0, 2),
            "generation_ms": round(generation_ms, 2),
            "total_ms": round((time.perf_counter() - self._run_started) * 1000, 2),
        }
        await self._emit(
            "done",
            {
                "message_id": str(request.message_id),
                "trace_id": self._trace_id,
                "finish_reason": finish_reason,
                "usage": usage,
                "timings": timings,
                "citations": citations,
                "steps": steps,
                "model": self.settings.chat_model,
            },
        )
        return {"answer": answer, "citations": citations, "steps": steps}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _writer_messages(self, state: AgentState) -> list[dict[str, str]]:
        request = state["request"]
        retrieval = state.get("retrieval")
        selected = retrieval.selected if retrieval else []
        citations = state.get("citations") or []
        tool_results = state.get("tool_results") or []
        blocks: list[str] = []
        for citation, candidate in zip(citations, selected, strict=False):
            page = citation.get("page_no") or "未知"
            blocks.append(
                f"[{citation['index']}] 《{citation['document_title']}》 第 {page} 页\n"
                f"{candidate.content}"
            )
        tool_text = json.dumps(tool_results, ensure_ascii=False) if tool_results else "无"
        user_prompt = f"""用户问题：
{request.query}

【证据】
{chr(10).join(blocks) if blocks else "无"}

【工具结果】
{tool_text}

请输出 Markdown 结构化报告，结论与处置建议中的事实必须带 [n] 角标。"""
        messages: list[dict[str, str]] = [{"role": "system", "content": _WRITER_SYSTEM_PROMPT}]
        for item in request.history[-4:]:
            messages.append({"role": item.role, "content": item.content[:1000]})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    @staticmethod
    def _normalize_plan(payload: dict[str, Any], max_steps: int) -> list[dict[str, Any]]:
        raw_steps = payload.get("steps") if isinstance(payload, dict) else None
        if not isinstance(raw_steps, list):
            return OpsAssistant._fallback_plan()
        allowed_actions = {"retrieve", "tool", "review", "answer"}
        plan: list[dict[str, Any]] = []
        for item in raw_steps[:max_steps]:
            if not isinstance(item, dict):
                continue
            action = item.get("action")
            description = str(item.get("description") or "").strip()
            if action not in allowed_actions or not description:
                continue
            step: dict[str, Any] = {
                "step_index": len(plan),
                "action": action,
                "description": description[:300],
            }
            tool_name = item.get("tool_name")
            if tool_name:
                step["tool_name"] = str(tool_name)[:64]
            plan.append(step)
        return plan or OpsAssistant._fallback_plan()

    @staticmethod
    def _fallback_plan() -> list[dict[str, Any]]:
        return [
            {
                "step_index": 0,
                "action": "retrieve",
                "description": "检索知识库中的规范、SOP 与历史处置记录。",
            },
            {
                "step_index": 1,
                "action": "tool",
                "description": "分析相关服务近期错误日志与运行状态。",
                "tool_name": "analyze_service_logs",
            },
            {
                "step_index": 2,
                "action": "review",
                "description": "核查证据是否足以支撑结论，必要时拒答。",
            },
            {
                "step_index": 3,
                "action": "answer",
                "description": "生成带 [n] 角标的结构化处置报告。",
            },
        ]

    @staticmethod
    def _service_from_query(query: str) -> str:
        match = re.search(r"\b([a-z][a-z0-9]+(?:-[a-z0-9]+)+)\b", query.lower())
        return match.group(1) if match else "order-api"

    @staticmethod
    def _mock_log_analysis(service: str) -> dict[str, Any]:
        error_rate = 0.027 if "order" in service else 0.013
        return {
            "service": service,
            "environment": "gray",
            "window_minutes": 30,
            "sample_size": 18420,
            "error_rate": error_rate,
            "threshold": 0.01,
            "top_error_code": "UPSTREAM_TIMEOUT",
            "observed_at": _iso_now(),
        }

    @staticmethod
    def _mock_service_status(service: str) -> dict[str, Any]:
        return {
            "service": service,
            "status": "degraded",
            "replicas": 6,
            "ready_replicas": 6,
            "gray_percent": 5,
            "last_deploy": "2026-11-24T10:30:00Z",
        }

    @staticmethod
    def _citation_payload(candidate: ChunkCandidate) -> dict[str, Any]:
        return {
            "index": candidate.citation_index,
            "chunk_id": candidate.chunk_id,
            "parent_chunk_id": candidate.parent_chunk_id,
            "document_id": candidate.document_id,
            "document_title": candidate.document_title,
            "page_no": candidate.page_no,
            "bbox": candidate.bbox,
            "char_start": candidate.char_start,
            "char_end": candidate.char_end,
            "quote": (candidate.content or candidate.document_title)[:500],
            "rerank_score": candidate.rerank_score,
        }

    def _record_usage(self, usage: dict[str, Any] | None) -> None:
        if not usage:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            self._usage[key] = int(self._usage.get(key, 0)) + int(usage.get(key) or 0)
        if usage.get("model"):
            self._usage["model"] = str(usage["model"])

    def _usage_event(self, request: ChatStreamRequest) -> dict[str, Any]:
        return {
            "prompt_tokens": int(self._usage.get("prompt_tokens", 0)),
            "completion_tokens": int(self._usage.get("completion_tokens", 0)),
            "total_tokens": int(self._usage.get("total_tokens", 0)),
            "model": str(self._usage.get("model") or self.settings.chat_model),
        }

    def _step_payload(
        self,
        node: str,
        status: str,
        title: str,
        latency_ms: float,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        return {
            "step_index": _NODE_INDEX[node],
            "node": node,
            "status": status,
            "title": title,
            "tool_name": tool_name,
            "latency_ms": round(float(latency_ms), 2),
        }

    def _with_step(
        self,
        state: AgentState,
        node: str,
        status: str,
        title: str,
        latency_ms: float,
        tool_name: str | None = None,
    ) -> list[dict[str, Any]]:
        steps = list(state.get("steps", []))
        steps.append(self._step_payload(node, status, title, latency_ms, tool_name))
        return steps

    def _error_data(self, exc: Exception) -> dict[str, Any]:
        message_id = str(self._request.message_id) if self._request else None
        if isinstance(exc, (LLMNotConfigured, LLMError)):
            code = "llm_unavailable"
            stage = "generation"
        elif isinstance(exc, RetrievalError):
            code = "retrieval_failed"
            stage = "agent"
        else:
            code = "internal_error"
            stage = "agent"
        return {
            "message_id": message_id,
            "error": {
                "code": code,
                "message": _safe_message(exc),
                "retryable": code in {"llm_unavailable", "retrieval_failed"},
                "trace_id": self._trace_id,
                "stage": stage,
            },
        }


def _iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _safe_message(exc: Exception) -> str:
    return (str(exc) or type(exc).__name__)[:500]


def _chunks(text: str, size: int) -> list[str]:
    return [text[start : start + size] for start in range(0, len(text), size)] or [""]
