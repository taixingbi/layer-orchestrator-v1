"""Route decision schema: nested route_detail + legacy flat route mapping."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LegacyRoute = Literal["rag", "direct_reply", "clarify", "reject", "tool"]
InternalIntentName = Literal[
    "identity",
    "greeting",
    "help",
    "capabilities",
    "clarify",
    "reject",
]
ToolName = Literal["rag_private_kb", "github_search", "web_search"]

class InternalIntentRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["internal_intent"] = "internal_intent"
    name: InternalIntentName
    confidence: float = 1.0
    reason: str = ""


class ToolRoute(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["tool"] = "tool"
    name: ToolName
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
            return "tool"
    return "tool"


def is_rag_private_kb_tool(route: str, route_detail: Any = None) -> bool:
    """True when the decision targets rag_private_kb (legacy flat route was 'rag')."""
    r = (route or "").strip().lower()
    if r == "rag":
        return True
    if r != "tool":
        return False
    parsed = parse_route_detail(route_detail)
    return isinstance(parsed, ToolRoute) and parsed.name == "rag_private_kb"


def routes_equivalent(expected: str, actual: str, route_detail: Any = None) -> bool:
    """Eval compat: legacy expected_route 'rag' matches flat 'tool' + rag_private_kb."""
    exp = (expected or "").strip().lower()
    act = (actual or "").strip().lower()
    if exp == act:
        return True
    if exp == "rag" and act == "tool" and is_rag_private_kb_tool("tool", route_detail):
        return True
    return False


def route_detail_from_legacy(
    route: str,
    *,
    reason: str = "",
    confidence: float = 1.0,
) -> RouteDetail:
    """Best-effort nested route_detail from legacy flat route (for eval compat)."""
    r = (route or "rag").strip().lower()
    if r == "rag":
        return ToolRoute(name="rag_private_kb", confidence=confidence, reason=reason)
    if r == "tool":
        return ToolRoute(name="github_search", confidence=confidence, reason=reason)
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
        try:
            return InternalIntentRoute.model_validate(raw)
        except ValidationError:
            return None
    if t == "tool":
        try:
            return ToolRoute.model_validate(raw)
        except ValidationError:
            return None
    return None
