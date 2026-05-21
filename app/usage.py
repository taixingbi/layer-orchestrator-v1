"""Token usage normalization and aggregation for API responses."""

from __future__ import annotations

from typing import Any, Dict, Optional

_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def empty_usage() -> Dict[str, int]:
    """Flat zero totals (no nested phase keys)."""
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def normalize_usage(raw: Any) -> Optional[Dict[str, int]]:
    """OpenAI-style usage dict or None if not parseable."""
    if not isinstance(raw, dict):
        return None
    prompt = raw.get("prompt_tokens")
    completion = raw.get("completion_tokens")
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


def build_usage_payload(
    *,
    intent_router: Optional[Dict[str, int]] = None,
    rag: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Flat totals plus optional nested intent_router / rag when data exists."""
    ir = normalize_usage(intent_router) if intent_router else None
    rg = normalize_usage(rag) if rag else None
    parts = [p for p in (ir, rg) if p]
    flat = merge_usage(*parts) if parts else empty_usage()
    payload: Dict[str, Any] = dict(flat)
    if ir:
        payload["intent_router"] = ir
    if rg:
        payload["rag"] = rg
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


def usage_from_rag_json(data: Any) -> Optional[Dict[str, int]]:
    """Extract top-level usage from RAG HTTP JSON."""
    if not isinstance(data, dict):
        return None
    return normalize_usage(data.get("usage"))
