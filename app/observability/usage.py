"""Token usage normalization and aggregation for API responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def empty_usage() -> Dict[str, int]:
    """Flat zero totals (no nested phase keys)."""
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def normalize_usage(raw: Any) -> Optional[Dict[str, int]]:
    """OpenAI-style usage dict or None if not parseable."""
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    if prompt is None:
        prompt = raw.get("input_tokens")
    completion = raw.get("completion_tokens")
    if completion is None:
        completion = raw.get("output_tokens")
    total = raw.get("total_tokens")
    try:
        p = int(prompt) if prompt is not None else 0
        c = int(completion) if completion is not None else 0
    except (TypeError, ValueError):
        return None
    if total is not None:
        try:
            t = int(total)
        except (TypeError, ValueError):
            t = p + c
    else:
        t = p + c
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}


def merge_usage(*parts: Optional[Dict[str, int]]) -> Dict[str, int]:
    """Sum token fields across normalized usage dicts."""
    out = empty_usage()
    for part in parts:
        if not part:
            continue
        norm = normalize_usage(part)
        if not norm:
            continue
        for key in _USAGE_KEYS:
            out[key] += norm.get(key, 0)
    return out


def rag_usage_flat(raw: Any) -> Optional[Dict[str, int]]:
    """Flat token totals from RAG usage (prefers `total`, else sums phase keys)."""
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("total"), dict):
        return normalize_usage(raw.get("total"))
    parts: List[Optional[Dict[str, int]]] = []
    for key in ("chat", "follow_up_chat"):
        part = raw.get(key)
        if isinstance(part, dict):
            norm = normalize_usage(part)
            if norm:
                parts.append(norm)
    if parts:
        return merge_usage(*parts)
    return normalize_usage(raw)


def rag_usage_detail(raw: Any) -> Optional[Dict[str, Any]]:
    """RAG usage for API `usage.rag`: flat totals plus optional chat / follow_up_chat."""
    if not isinstance(raw, dict):
        return None
    flat = rag_usage_flat(raw)
    out: Dict[str, Any] = dict(flat) if flat else {}
    for key in ("chat", "follow_up_chat"):
        part = raw.get(key)
        if isinstance(part, dict):
            norm = normalize_usage(part)
            if norm:
                out[key] = norm
    return out or None


def build_usage_payload(
    *,
    intent_router: Optional[Dict[str, int]] = None,
    rag: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Flat totals plus optional nested intent_router / rag when data exists."""
    ir = normalize_usage(intent_router) if intent_router else None
    rg_flat = rag_usage_flat(rag)
    rg_detail = rag_usage_detail(rag)
    parts = [p for p in (ir, rg_flat) if p]
    flat = merge_usage(*parts) if parts else empty_usage()
    payload: Dict[str, Any] = dict(flat)
    if ir:
        payload["intent_router"] = ir
    if rg_detail:
        payload["rag"] = rg_detail
    return payload


def usage_from_langchain_message(msg: Any) -> Optional[Dict[str, int]]:
    """Extract usage from LangChain AIMessage (OpenAI gateway compat)."""
    if msg is None:
        return None
    meta = getattr(msg, "response_metadata", None)
    if isinstance(meta, dict):
        tu = meta.get("token_usage") or meta.get("usage")
        norm = normalize_usage(tu)
        if norm:
            return norm
    um = getattr(msg, "usage_metadata", None)
    if um is not None:
        if hasattr(um, "model_dump"):
            um = um.model_dump()
        norm = normalize_usage(um)
        if norm:
            return norm
    return None


def usage_from_rag_json(data: Any) -> Optional[Dict[str, Any]]:
    """Extract usage from RAG HTTP JSON (flat or nested chat / follow_up_chat / total)."""
    if not isinstance(data, dict):
        return None
    raw = data.get("usage")
    if not isinstance(raw, dict):
        return None
    return rag_usage_detail(raw)
