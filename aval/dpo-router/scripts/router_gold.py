"""Shared gold CSV → router completion helpers (DPO + SFT dataset builders)."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.rewrite import (
    CANDIDATE_NAME,
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    rewrite_to_third_person,
)
from app.schemas.route import (
    CANONICAL_ROUTES,
    normalize_gold_expected_route,
    normalize_legacy_route_to_canonical,
)

DEFAULT_SKIP_BASENAMES = frozenset(
    {
        "router_greeting",
        "router_identity",
        "router_help",
        "router_capabilities",
        "router_reject",
    }
)

_DIRECT_REPLY_INTENT_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"^(hi|hello|hey)\b", re.I), "greeting"),
    (re.compile(r"how are you", re.I), "greeting"),
    (re.compile(r"\b(name|who (are|created) you|yourself)\b", re.I), "identity"),
    (re.compile(r"\b(what can you do|capabilities)\b", re.I), "capabilities"),
]


@dataclass(frozen=True)
class GoldRow:
    question: str
    expected_route: str
    source_file: str
    expected_tool: Optional[str] = None
    history: Optional[List[Dict[str, str]]] = None


def load_router_system_prompt(version: str) -> str:
    from app.core.intent_router import _resolve_router_system_content

    content, _ = _resolve_router_system_content(
        body_override=None,
        requested_version=version,
        default_version=version,
    )
    return content


def canonical_expected_route(row: GoldRow) -> str:
    er = normalize_gold_expected_route(row.expected_route)
    if er == "help" and row.expected_route.strip().lower() == "direct_reply":
        for pat, intent in _DIRECT_REPLY_INTENT_PATTERNS:
            if pat.search(row.question):
                return intent
        return "help"
    if er == "github_search" and row.expected_tool:
        return normalize_legacy_route_to_canonical("tool", {"type": "tool", "name": row.expected_tool})
    if er in CANONICAL_ROUTES:
        return er
    return normalize_legacy_route_to_canonical(er)


def parse_gold_csv(path: Path) -> List[GoldRow]:
    rows: List[GoldRow] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for raw in reader:
            question = (raw.get("question") or "").strip()
            if not question:
                continue
            expected_route = (raw.get("expected_route") or "").strip().lower()
            if not expected_route:
                continue
            expected_tool = (raw.get("expected_tool") or raw.get("expected_tool_name") or "").strip() or None
            history: Optional[List[Dict[str, str]]] = None
            if "history_json" in fieldnames and raw.get("history_json"):
                try:
                    parsed = json.loads(raw["history_json"])
                    if isinstance(parsed, list):
                        history = parsed
                except json.JSONDecodeError:
                    pass
            rows.append(
                GoldRow(
                    question=question,
                    expected_route=expected_route,
                    source_file=path.name,
                    expected_tool=expected_tool,
                    history=history,
                )
            )
    return rows


def _rewritten_question(row: GoldRow, canonical_route: str) -> str:
    q = row.question.strip()
    if canonical_route in ("rag_private_kb", "github_search", "web_search"):
        return rewrite_to_third_person(q)
    return q


def _static_answer_for_chosen(row: GoldRow, canonical_route: str) -> Optional[str]:
    if canonical_route == "reject":
        return None
    if canonical_route == "clarify":
        return "Please clarify your question."
    if canonical_route == "greeting":
        return f"Hello, I'm an assistant for questions about {CANDIDATE_NAME}'s profile and related topics."
    if canonical_route == "identity":
        return f"I'm an AI assistant focused on {CANDIDATE_NAME}'s profile and organizational knowledge."
    if canonical_route == "capabilities":
        return (
            f"I can answer questions about {CANDIDATE_NAME}'s profile, visa and work authorization "
            "from your knowledge base, and related topics."
        )
    return None


def build_router_completion(row: GoldRow, *, label: str = "gold") -> Dict[str, Any]:
    route = canonical_expected_route(row)
    return {
        "rewritten_question": _rewritten_question(row, route),
        "route": route,
        "confidence": 0.95,
        "reason": f"{label}: expected {route}",
        "static_answer": _static_answer_for_chosen(row, route),
        "repo": None,
    }


def router_llm_eligible(row: GoldRow) -> bool:
    """Train only ambiguous LLM-router cases (skip seed, guard, deterministic github)."""
    base = Path(row.source_file).stem
    if base in DEFAULT_SKIP_BASENAMES:
        return False
    er = canonical_expected_route(row)
    if er in ("reject", "clarify"):
        return False
    if not (row.question or "").strip():
        return False
    if er == "github_search":
        from app.core.github_route import match_github_search

        if match_github_search(row.question) is not None:
            return False
    return True


def build_user_message(row: GoldRow) -> str:
    hist: List[Tuple[str, str]] = []
    if row.history:
        for turn in row.history:
            role = (turn.get("role") or "").strip().lower()
            content = (turn.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                hist.append((role, content))
    hist_block = format_history_for_prompt(hist, REWRITE_HISTORY_MAX_LINES)
    q = row.question.strip()
    if hist_block:
        return f"History:\n{hist_block}\n\nLatest question:\n{q}"
    return f"History:\n(none)\n\nLatest question:\n{q}"


def completion_json(completion: Dict[str, Any]) -> str:
    return json.dumps(completion, ensure_ascii=False, separators=(",", ":"))


def iter_gold_rows(
    gold_data_dir: Path,
    *,
    include_seed_faq: bool,
    include_hack: bool,
) -> Iterable[GoldRow]:
    skip = set(DEFAULT_SKIP_BASENAMES)
    if include_seed_faq:
        skip.discard("router_greeting")
        skip.discard("router_identity")
        skip.discard("router_help")
        skip.discard("router_capabilities")
    if include_hack:
        skip.discard("router_reject")
    for path in sorted(gold_data_dir.glob("**/*.csv")):
        if path.stem in skip:
            continue
        yield from parse_gold_csv(path)


def val_split(question: str, val_ratio: float) -> bool:
    if val_ratio <= 0:
        return False
    h = sum(ord(c) for c in question) % 1000
    return h < int(val_ratio * 1000)


def write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
