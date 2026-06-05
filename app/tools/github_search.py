"""GitHub repo search via MCP github_search."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from ..config import settings
from ..schemas.tool import ToolResult
from .mcp_client import call_mcp_tool


async def run_github_search(
    question: str,
    *,
    repo: Optional[str] = None,
    request_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    rag_user: Optional[Dict[str, str]] = None,
    conversation_id: str = "",
    is_new_conversation: bool = False,
    on_delta: Optional[Callable[[str], None]] = None,
) -> ToolResult:
    base = settings.mcp_github_base_url
    if not base:
        raise ValueError("MCP_GITHUB_BASE_URL is not set")
    args: Dict[str, object] = {
        "question": question,
        "stream": True,
    }
    if repo:
        args["repo"] = repo
    if conversation_id:
        args["conversation_id"] = conversation_id
    return await call_mcp_tool(
        base_url=base,
        tool_name="github_search",
        arguments=args,
        request_id=request_id,
        session_id=session_id,
        trace_id=trace_id,
        rag_user=rag_user,
        conversation_id=conversation_id,
        is_new_conversation=is_new_conversation,
        on_delta=on_delta,
    )
