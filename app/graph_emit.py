"""Emit pipeline state events into LangGraph configurable (SSE queue)."""

from typing import Any, Optional

from langchain_core.runnables import RunnableConfig


async def emit_pipeline_state(config: Optional[RunnableConfig], **kwargs: Any) -> None:
    fn = ((config or {}).get("configurable") or {}).get("emit_state")
    if callable(fn):
        await fn(**kwargs)
