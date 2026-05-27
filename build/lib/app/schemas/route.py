"""Route decision schema: canonical route + envelope route_detail."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, ValidationError

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

CanonicalRoute = Literal[
    "rag_private_kb",
    "github_search",
    "web_search",
    "greeting",
    "identity",
    "help",
    "capabilities",
    "clarify",
    "reject",
]

TOOL_ROUTES = frozenset({"rag_private_kb", "github_search", "web_search"})
INTERNAL_ROUTES = frozenset(
    {"greeting", "identity", "help", "capabilities", "clarify", "reject"}
)
CANONICAL_ROUTES = TOOL_ROUTES | INTERNAL_ROUTES

# Gold CSV migration aliases (eval only).
_GOLD_EXPECTED_ALIASES: Dict[str, str] = {
    "rag": "rag_private_kb",
    "tool": "github_search",
    "direct_reply": "help",
}


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


def is_tool_route(route: str) -> bool:
    return (route or "").strip().lower() in TOOL_ROUTES


def is_internal_route(route: str) -> bool:
    return (route or "").strip().lower() in INTERNAL_ROUTES


def is_rag_private_kb_route(route: str) -> bool:
    return (route or "").strip().lower() == "rag_private_kb"


def is_rag_private_kb_tool(route: str, route_detail: Any = None) -> bool:
    """Compat: True for canonical rag_private_kb or legacy rag/tool + detail."""
    if is_rag_private_kb_route(route):
        return True
    r = (route or "").strip().lower()
    if r == "rag":
        return True
    if r != "tool":
        return False
    parsed = parse_route_detail(route_detail)
    return isinstance(parsed, ToolRoute) and parsed.name == "rag_private_kb"


def normalize_legacy_route_to_canonical(
    route: str,
    route_detail: Any = None,
) -> str:
    """Map legacy flat route (+ optional route_detail) to canonical route."""
    r = (route or "").strip().lower()
    if r in CANONICAL_ROUTES:
        return r
    if r == "rag":
        return "rag_private_kb"
    if r == "tool":
        parsed = parse_route_detail(route_detail)
        if isinstance(parsed, ToolRoute):
            return parsed.name
        return "github_search"
    if r == "clarify":
        return "clarify"
    if r == "reject":
        return "reject"
    if r == "direct_reply":
        parsed = parse_route_detail(route_detail)
        if isinstance(parsed, InternalIntentRoute):
            name = parsed.name
            if name in INTERNAL_ROUTES:
                return name
        return "help"
    return "rag_private_kb"


def canonical_to_route_detail(
    route: str,
    *,
    confidence: float = 1.0,
    reason: str = "",
    repo: Optional[str] = None,
) -> RouteDetail:
    """Derive envelope route_detail from canonical route (client boundary only)."""
    r = normalize_legacy_route_to_canonical(route)
    if r in TOOL_ROUTES:
        return ToolRoute(
            name=r,  # type: ignore[arg-type]
            confidence=confidence,
            reason=reason,
            repo=repo,
        )
    return InternalIntentRoute(
        name=r,  # type: ignore[arg-type]
        confidence=confidence,
        reason=reason,
    )


def canonical_from_route_detail(detail: Any) -> str:
    """Map nested route_detail to canonical route."""
    if isinstance(detail, ToolRoute):
        return detail.name
    if isinstance(detail, InternalIntentRoute):
        return detail.name
    if isinstance(detail, dict):
        t = detail.get("type")
        name = str(detail.get("name") or "").strip().lower()
        if t == "tool" and name in TOOL_ROUTES:
            return name
        if t == "internal_intent" and name in INTERNAL_ROUTES:
            return name
    return "rag_private_kb"


def normalize_gold_expected_route(expected: str) -> str:
    """Normalize gold CSV expected_route to canonical (incl. legacy aliases)."""
    exp = (expected or "").strip().lower()
    return _GOLD_EXPECTED_ALIASES.get(exp, exp)


def routes_equivalent(expected: str, actual: str, route_detail: Any = None) -> bool:
    """Eval: compare canonical routes; gold may still use legacy labels."""
    exp = normalize_gold_expected_route(expected)
    act = normalize_legacy_route_to_canonical(actual, route_detail)
    if exp == act:
        return True
    # Legacy eval: expected rag vs actual tool+rag_private_kb detail
    if exp == "rag_private_kb" and act == "github_search":
        if is_rag_private_kb_tool("tool", route_detail):
            return True
    return False


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


def route_detail_from_legacy(
    route: str,
    *,
    reason: str = "",
    confidence: float = 1.0,
) -> RouteDetail:
    """Best-effort nested route_detail from legacy flat route (gold/DPO migration)."""
    canonical = normalize_legacy_route_to_canonical(route)
    return canonical_to_route_detail(canonical, confidence=confidence, reason=reason)


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
