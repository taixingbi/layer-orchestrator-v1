"""Route decision schema: nested route_detail + legacy flat route mapping."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

LegacyRoute = Literal["rag", "direct_reply", "clarify", "reject", "tool"]
InternalIntentName = Literal[
    "identity",
    "greeting",
    "help",
    "capabilities",
    "clarify",
    "reject",
]
ToolName = Literal["user_profile", "github_repo_search", "web_search"]


class InternalIntentRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["internal_intent"] = "internal_intent"
    name: str
    confidence: float = 1.0
    reason: str = ""


class ToolRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["tool"] = "tool"
    name: str
    confidence: float = 1.0
    reason: str = ""
    repo: Optional[str] = None


RouteDetail = Union[InternalIntentRoute, ToolRoute]


def legacy_route_from_detail(detail: Any) -> str:
    """Map nested route_detail to flat route string for backward compatibility."""
    if isinstance(detail, InternalIntentRoute):
        name = detail.name
        if name in ("clarify",):
            return "clarify"
        if name in ("reject",):
            return "reject"
        return "direct_reply"
    if isinstance(detail, ToolRoute):
        if detail.name == "user_profile":
            return "rag"
        return "tool"
    if isinstance(detail, dict):
        t = detail.get("type")
        name = str(detail.get("name") or "")
        if t == "internal_intent":
            if name == "clarify":
                return "clarify"
            if name == "reject":
                return "reject"
            return "direct_reply"
        if t == "tool":
            if name == "user_profile":
                return "rag"
            return "tool"
    return "rag"


def route_detail_from_legacy(
    route: str,
    *,
    reason: str = "",
    confidence: float = 1.0,
) -> RouteDetail:
    """Best-effort nested route_detail from legacy flat route (for eval compat)."""
    r = (route or "rag").strip().lower()
    if r == "rag":
        return ToolRoute(name="user_profile", confidence=confidence, reason=reason)
    if r == "tool":
        return ToolRoute(name="github_repo_search", confidence=confidence, reason=reason)
    if r == "clarify":
        return InternalIntentRoute(name="clarify", confidence=confidence, reason=reason)
    if r == "reject":
        return InternalIntentRoute(name="reject", confidence=confidence, reason=reason)
    return InternalIntentRoute(name="help", confidence=confidence, reason=reason or "direct_reply")


def route_detail_to_dict(detail: Any) -> Dict[str, Any]:
    if hasattr(detail, "model_dump"):
        return detail.model_dump(exclude_none=True)
    if isinstance(detail, dict):
        return dict(detail)
    return {}


def parse_route_detail(raw: Any) -> Optional[RouteDetail]:
    if raw is None:
        return None
    if isinstance(raw, (InternalIntentRoute, ToolRoute)):
        return raw
    if not isinstance(raw, dict):
        return None
    t = raw.get("type")
    if t == "internal_intent":
        return InternalIntentRoute.model_validate(raw)
    if t == "tool":
        return ToolRoute.model_validate(raw)
    return None
