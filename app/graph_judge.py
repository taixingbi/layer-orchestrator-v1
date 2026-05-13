"""LangGraph judge node: answer quality check and retry signal."""
import logging
import time
from typing import List

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from .agent_answer_judge import evaluate_answer
from .agent_graph_state import AgentState
from .graph_emit import emit_pipeline_state
from .pipeline_state import utc_now_iso
from .request_context import bind_pipeline_phase
from .utils import extract_message_content, message_role

MAX_RETRIES = 1
_judge_log = logging.getLogger("layer_orchestrator.graph_judge")


async def judge_node(state: AgentState, config: RunnableConfig):
    messages = state["messages"]
    retry_count = state.get("retry_count", 0)
    phase_name = "judge_retry" if retry_count > 0 else "judge"
    async with bind_pipeline_phase(phase_name):
        _judge_log.debug("judge_started", extra={"event": "judge_started"})
        if retry_count >= MAX_RETRIES:
            _judge_log.debug(
                "judge_skipped_max_retries",
                extra={"event": "judge_skipped_max_retries", "gateway_meta": {"retry_count": retry_count}},
            )
            skipped_ts = utc_now_iso()
            await emit_pipeline_state(
                config,
                phase=phase_name,
                status="skipped",
                ui_message="Judge skipped (max retries reached)",
                started_at=skipped_ts,
                ended_at=skipped_ts,
                metadata={"retry_count": retry_count},
            )
            return {"judge_passed": True}
        cfg = (config or {}).get("configurable") or {}
        question = (cfg.get("original_question") or "").strip()
        answer = ""
        tool_contents: List[str] = []
        for m in messages:
            role = message_role(m)
            if role in ("human", "user"):
                continue
            elif role == "ai":
                tcalls = getattr(m, "tool_calls", None) or (
                    m.get("tool_calls") if isinstance(m, dict) else None
                )
                if tcalls:
                    continue
                c = extract_message_content(m)
                if (c or "").strip():
                    answer = c
            elif role == "tool":
                tool_contents.append(extract_message_content(m))
        if not question:
            for m in messages:
                if message_role(m) in ("human", "user"):
                    question = extract_message_content(m)
                    break
        evidence = "\n".join(f"[E{i+1}] {c}" for i, c in enumerate(tool_contents) if c) or None
        judge_started_at = utc_now_iso()
        t_judge = time.perf_counter()
        await emit_pipeline_state(
            config,
            phase=phase_name,
            status="running",
            ui_message="Evaluating answer quality...",
            started_at=judge_started_at,
            metadata={"retry_count": retry_count},
        )
        passed, feedback = await evaluate_answer(
            question,
            answer,
            evidence=evidence,
            request_id=cfg.get("request_id"),
            session_id=cfg.get("session_id"),
            trace_id=cfg.get("trace_id"),
            conversation_id=cfg.get("conversation_id"),
            is_new_conversation=bool(cfg.get("is_new_conversation")),
        )
        will_retry = not passed and retry_count < MAX_RETRIES
        _judge_log.debug(
            "judge_evaluated",
            extra={
                "event": "judge_evaluated",
                "gateway_meta": {
                    "retry_count": retry_count,
                    "passed": passed,
                    "feedback_preview": (feedback or "")[:120] or None,
                },
            },
        )
        await emit_pipeline_state(
            config,
            phase=phase_name,
            status="completed",
            ui_message="Judge completed",
            started_at=judge_started_at,
            ended_at=utc_now_iso(),
            latency_ms=(time.perf_counter() - t_judge) * 1000,
            metadata={
                "retry_count": retry_count,
                "passed": passed,
                "feedback_preview": (feedback or "")[:120] or None,
                "will_retry": will_retry,
            },
        )
        if passed or retry_count >= MAX_RETRIES:
            return {"judge_passed": True}
        return {
            "judge_passed": False,
            "messages": [HumanMessage(content=f"The previous answer was not good enough. Reason: {feedback} Please improve your answer.")],
            "retry_count": retry_count + 1,
        }
