"""Deterministic github_repo_search routing (HuntAI / layer repo / gateway architecture)."""

from __future__ import annotations

import re
from typing import Optional

from ..schemas.route import ToolRoute

_HUNTAI_RE = re.compile(r"\bhunt\s*ai\b|\bhuntai\b", re.I)
_REPO_SIGNAL_RE = re.compile(
    r"\b("
    r"gateway|orchestrator|layer-orchestrator|github|readme|"
    r"repo(?:sitory)?|architecture|codebase|code\s*layout|"
    r"ask_repo|mcp|split\s+orchestrator|layer-orchestrator-v1"
    r")\b",
    re.I,
)
_LAYER_REPO_RE = re.compile(
    r"\b(taixingbi/layer-orchestrator-v1|layer-orchestrator-v1|layer-orchestrator)\b",
    re.I,
)
_DESIGN_GATEWAY_RE = re.compile(
    r"\b(design|architect|structure|layout|split|explain|how\s+to)\b",
    re.I,
)
_DEFAULT_REPO = "taixingbi/layer-orchestrator-v1"


def _extract_repo(question: str) -> Optional[str]:
    m = re.search(r"\b(taixingbi/layer-orchestrator-v\d+)\b", question, re.I)
    if m:
        return m.group(1)
    if _LAYER_REPO_RE.search(question):
        return _DEFAULT_REPO
    return None


def match_github_repo_search(question: str) -> Optional[ToolRoute]:
    """Return ToolRoute when the ask is clearly HuntAI/layer GitHub repo architecture."""
    q = (question or "").strip()
    if not q:
        return None

    has_huntai = bool(_HUNTAI_RE.search(q))
    has_repo_signal = bool(_REPO_SIGNAL_RE.search(q))
    has_layer_repo = bool(_LAYER_REPO_RE.search(q))
    has_design = bool(_DESIGN_GATEWAY_RE.search(q))

    matched = (
        (has_huntai and has_repo_signal)
        or (has_layer_repo and (has_repo_signal or has_design))
        or (has_repo_signal and has_design and "gateway" in q.lower())
    )
    if not matched:
        return None

    repo = _extract_repo(q)
    return ToolRoute(
        name="github_repo_search",
        confidence=0.99,
        reason="Deterministic: HuntAI/layer repo or gateway architecture question",
        repo=repo,
    )
