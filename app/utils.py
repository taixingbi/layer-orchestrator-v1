"""Shared utilities for message/content extraction."""
from typing import Any, List, Optional


def message_role(msg: Any) -> Optional[str]:
    """LangChain ``type`` or OpenAI-style dict ``role`` / ``type``."""
    if isinstance(msg, dict):
        return msg.get("type") or msg.get("role")
    return getattr(msg, "type", None)


def extract_message_content(msg: Any) -> str:
    """Extract text content from a message (dict or object). Handles str and list content."""
    content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def first_user_text(messages: List[Any]) -> str:
    """First human/user message body (rewritten question in our graphs)."""
    for m in messages:
        if message_role(m) in ("human", "user"):
            return extract_message_content(m)
    return ""


def last_ai_content(messages: List[Any]) -> str:
    """Return the text content of the last AI message in the list."""
    for msg in reversed(messages):
        if message_role(msg) in ("ai", "assistant"):
            return extract_message_content(msg) or ""
    return ""
