"""User profile tool via MCP rag_query (stream) or HTTP RAG fallback."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from ..config import mcp_rag_enabled, settings
from ..clients.rag_http import query_rag_http_with_meta
from ..schemas.tool import ToolResult
from ..observability.usage import usage_from_rag_json
from .mcp_client import call_mcp_tool


def _use_mcp_rag() -> bool:
    return mcp_rag_enabled()


async def run_user_profile(
    question: str,
    *,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    rag_user: Optional[Dict[str, str]] = None,
    conversation_id: str = "",
    is_new_conversation: bool = False,
    on_delta: Optional[Callable[[str], None]] = None,
) -> ToolResult:
    if _use_mcp_rag():
        result = await call_mcp_tool(
            base_url=settings.mcp_rag_base_url or "",
            tool_name="rag_query",
            arguments={
                "question": question,
                "collection_base": settings.rag_collection_base,
                "conversation_id": conversation_id,
                "k": settings.rag_k,
                "k_max": settings.rag_k_max,
                "stream": True,
            },
            request_id=request_id,
            session_id=session_id,
            trace_id=trace_id,
            rag_user=rag_user,
            conversation_id=conversation_id,
            stream=True,
            on_delta=on_delta,
        )
        meta = dict(result.metadata or {})
        meta["transport"] = "mcp_rag"
        result.metadata = meta
        return result
    text, meta = await query_rag_http_with_meta(
        question,
        request_id,
        session_id,
        trace_id,
        user_id=(rag_user or {}).get("user_id", ""),
        user_roles=(rag_user or {}).get("user_roles", ""),
        user_groups=(rag_user or {}).get("user_groups", ""),
        user_teams=(rag_user or {}).get("user_teams", ""),
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
    )
    sidecar = (meta or {}).get("rag_tool_sidecar") or {}
    api = (meta or {}).get("rag_api_response") or {}
    usage = (meta or {}).get("usage") or usage_from_rag_json({"usage": api.get("usage")})
    return ToolResult(
        answer=text,
        citations=sidecar.get("citations") or api.get("citations") or [],
        follow_up_questions=sidecar.get("follow_up_questions") or api.get("follow_up_questions") or [],
        usage=usage,
        latency_ms=meta.get("rag_latency_ms") if meta else None,
        metadata={"transport": "http_rag"},
    )
