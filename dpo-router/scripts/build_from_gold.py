#!/usr/bin/env python3
"""Build router DPO JSONL from gold-test CSVs (+ optional eval result CSVs or live eval)."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.rewrite import (  # noqa: E402
    CANDIDATE_NAME,
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    rewrite_to_third_person,
)
from app.schemas.route import route_detail_from_legacy, route_detail_to_dict  # noqa: E402

DEFAULT_SKIP_BASENAMES = frozenset(
    {
        "router-gold-seed-faq",  # small-talk seed (no router LLM in prod)
        "router-gold-hack",  # injection guard (no router LLM in prod)
    }
)

# Heuristic internal_intent for direct_reply gold rows (meta / greeting / help).
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


def _load_router_system_prompt(version: str) -> str:
    from app.core.intent_router import _render_stored_router_prompt, _resolve_router_system_content

    content, _ = _resolve_router_system_content(
        body_override=None,
        requested_version=version,
        default_version=version,
    )
    return content


def _parse_gold_csv(path: Path) -> List[GoldRow]:
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


def _direct_reply_intent(question: str) -> str:
    for pat, intent in _DIRECT_REPLY_INTENT_PATTERNS:
        if pat.search(question):
            return intent
    return "help"


def _legacy_route_for_expected(row: GoldRow) -> str:
    er = row.expected_route
    if er == "rag":
        return "tool"
    return er


def _tool_name_for_expected(row: GoldRow) -> str:
    if row.expected_tool:
        return row.expected_tool
    if row.expected_route == "rag":
        return "rag_private_kb"
    if row.expected_route == "tool":
        return "github_search"
    return "rag_private_kb"


def _route_detail_dict(row: GoldRow) -> Dict[str, Any]:
    er = row.expected_route
    if er in ("rag", "tool"):
        return route_detail_to_dict(
            route_detail_from_legacy("tool", reason="gold label", confidence=0.95)
        ) | {"name": _tool_name_for_expected(row)}
    if er == "direct_reply":
        intent = _direct_reply_intent(row.question)
        return {"type": "internal_intent", "name": intent, "confidence": 0.95, "reason": "gold label"}
    if er == "clarify":
        return {"type": "internal_intent", "name": "clarify", "confidence": 0.95, "reason": "gold label"}
    if er == "reject":
        return {"type": "internal_intent", "name": "reject", "confidence": 0.99, "reason": "gold label"}
    return route_detail_to_dict(route_detail_from_legacy(er, reason="gold label", confidence=0.95))


def _rewritten_question(row: GoldRow) -> str:
    q = row.question.strip()
    er = row.expected_route
    if er in ("rag", "tool"):
        return rewrite_to_third_person(q)
    return q


def _direct_answer_for_chosen(row: GoldRow) -> Optional[str]:
    er = row.expected_route
    if er == "reject":
        return None
    if er == "clarify":
        return "Please clarify your question."
    if er == "direct_reply":
        intent = _direct_reply_intent(row.question)
        if intent == "greeting":
            return f"Hello, I'm an assistant for questions about {CANDIDATE_NAME}'s profile and related topics."
        if intent == "identity":
            return f"I'm an AI assistant focused on {CANDIDATE_NAME}'s profile and organizational knowledge."
        if intent == "capabilities":
            return (
                f"I can answer questions about {CANDIDATE_NAME}'s profile, visa and work authorization "
                "from your knowledge base, and related topics."
            )
        return None
    return None


def build_router_completion(row: GoldRow, *, label: str = "gold") -> Dict[str, Any]:
    route_detail = _route_detail_dict(row)
    legacy = _legacy_route_for_expected(row)
    return {
        "rewritten_question": _rewritten_question(row),
        "route_detail": route_detail,
        "direct_answer": _direct_answer_for_chosen(row),
        "reason": f"{label}: expected {row.expected_route}",
        "route": legacy,
    }


def _synthetic_rejected_row(row: GoldRow) -> GoldRow:
    """Opposite-route completion for DPO when live eval output is unavailable."""
    er = row.expected_route
    if er in ("rag", "tool"):
        return GoldRow(
            question=row.question,
            expected_route="direct_reply",
            source_file=row.source_file,
            history=row.history,
        )
    if er == "direct_reply":
        return GoldRow(
            question=row.question,
            expected_route="rag",
            source_file=row.source_file,
            history=row.history,
        )
    if er == "reject":
        return GoldRow(
            question=row.question,
            expected_route="direct_reply",
            source_file=row.source_file,
            history=row.history,
        )
    return GoldRow(
        question=row.question,
        expected_route="direct_reply",
        source_file=row.source_file,
        history=row.history,
    )


def _build_user_message(row: GoldRow) -> str:
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


def _completion_json(completion: Dict[str, Any]) -> str:
    return json.dumps(completion, ensure_ascii=False, separators=(",", ":"))


def _dpo_record(
    *,
    system_prompt: str,
    row: GoldRow,
    chosen: Dict[str, Any],
    rejected: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    user_content = _build_user_message(row)
    return {
        "prompt": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "chosen": _completion_json(chosen),
        "rejected": _completion_json(rejected),
        "meta": meta,
    }


def _read_result_csv(path: Path) -> Dict[str, Dict[str, str]]:
    """Map question -> eval result columns from gold-test result CSV."""
    out: Dict[str, Dict[str, str]] = {}
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            q = (raw.get("question") or "").strip()
            if not q:
                continue
            out[q] = {
                "expected_route": (raw.get("expected_route") or "").strip(),
                "actual_route": (raw.get("actual_route") or "").strip(),
                "route_match": (raw.get("route_match") or "").strip(),
                "rewritten_question": (raw.get("rewritten_question") or "").strip(),
                "actual_answer": (raw.get("actual_answer") or "").strip(),
            }
    return out


def _rejected_from_result(row: GoldRow, result: Dict[str, str]) -> Optional[Dict[str, Any]]:
    if result.get("route_match") == "true":
        return None
    actual = (result.get("actual_route") or "").strip().lower()
    if not actual:
        return None
    fake = GoldRow(
        question=row.question,
        expected_route=actual if actual != "tool" else "rag",
        source_file=row.source_file,
        expected_tool="rag_private_kb" if actual == "tool" else None,
        history=row.history,
    )
    completion = build_router_completion(fake, label="eval_actual")
    rw = (result.get("rewritten_question") or "").strip()
    if rw:
        completion["rewritten_question"] = rw
    ans = (result.get("actual_answer") or "").strip()
    if ans and actual == "direct_reply":
        completion["direct_answer"] = ans
    return completion


def _fetch_eval_decision(
    *,
    orchestrator_url: str,
    question: str,
    expected_route: str,
    router_prompt_version: str,
    timeout_s: float,
) -> Optional[Dict[str, Any]]:
    url = f"{orchestrator_url.rstrip('/')}/v1/orchestrator/eval/router"
    body = json.dumps(
        {
            "question": question,
            "expected_route": expected_route,
            "router_prompt_version": router_prompt_version,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return None
    route = (decision.get("route") or "").strip()
    route_detail = decision.get("route_detail")
    if not route:
        return None
    return {
        "rewritten_question": decision.get("rewritten_question") or question,
        "route_detail": route_detail if isinstance(route_detail, dict) else {},
        "direct_answer": decision.get("answer"),
        "reason": decision.get("reason") or "live eval",
        "route": route,
    }


def _iter_gold_rows(
    gold_data_dir: Path,
    *,
    include_seed_faq: bool,
    include_hack: bool,
) -> Iterable[GoldRow]:
    skip = set(DEFAULT_SKIP_BASENAMES)
    if include_seed_faq:
        skip.discard("router-gold-seed-faq")
    if include_hack:
        skip.discard("router-gold-hack")
    for path in sorted(gold_data_dir.glob("*.csv")):
        if path.stem in skip:
            continue
        yield from _parse_gold_csv(path)


def _val_split(question: str, val_ratio: float) -> bool:
    if val_ratio <= 0:
        return False
    h = sum(ord(c) for c in question) % 1000
    return h < int(val_ratio * 1000)


def build_dpo_dataset(
    *,
    gold_data_dir: Path,
    result_dir: Optional[Path],
    system_prompt: str,
    include_seed_faq: bool,
    include_hack: bool,
    fetch_live: bool,
    orchestrator_url: str,
    router_prompt_version: str,
    fetch_timeout_s: float,
    val_ratio: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "rows_total": 0,
        "pairs_written": 0,
        "skipped_match": 0,
        "rejected_source": {"result_csv": 0, "live_eval": 0, "synthetic": 0},
        "by_expected_route": {},
    }

    result_cache: Dict[str, Dict[str, Dict[str, str]]] = {}
    if result_dir and result_dir.is_dir():
        for rp in result_dir.glob("*.csv"):
            result_cache[rp.stem] = _read_result_csv(rp)

    for row in _iter_gold_rows(
        gold_data_dir,
        include_seed_faq=include_seed_faq,
        include_hack=include_hack,
    ):
        stats["rows_total"] += 1
        stats["by_expected_route"][row.expected_route] = stats["by_expected_route"].get(row.expected_route, 0) + 1

        chosen = build_router_completion(row, label="gold")
        rejected: Optional[Dict[str, Any]] = None
        rejected_src = "synthetic"

        stem = Path(row.source_file).stem
        result_row = result_cache.get(stem, {}).get(row.question)
        if result_row:
            rejected = _rejected_from_result(row, result_row)
            if rejected is not None:
                rejected_src = "result_csv"

        if rejected is None and fetch_live and orchestrator_url:
            live = _fetch_eval_decision(
                orchestrator_url=orchestrator_url,
                question=row.question,
                expected_route=row.expected_route,
                router_prompt_version=router_prompt_version,
                timeout_s=fetch_timeout_s,
            )
            if live and live.get("route") != chosen.get("route"):
                rejected = live
                rejected_src = "live_eval"
            elif live and live.get("route") == chosen.get("route"):
                stats["skipped_match"] += 1
                continue

        if rejected is None:
            rejected = build_router_completion(_synthetic_rejected_row(row), label="synthetic_rejected")

        meta = {
            "question": row.question,
            "expected_route": row.expected_route,
            "source_file": row.source_file,
            "rejected_source": rejected_src,
            "router_prompt_version": router_prompt_version,
        }
        record = _dpo_record(
            system_prompt=system_prompt,
            row=row,
            chosen=chosen,
            rejected=rejected,
            meta=meta,
        )
        stats["pairs_written"] += 1
        stats["rejected_source"][rejected_src] = stats["rejected_source"].get(rejected_src, 0) + 1
        if _val_split(row.question, val_ratio):
            val.append(record)
        else:
            train.append(record)

    return train, val, stats


def _write_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    dpo_root = Path(__file__).resolve().parents[1]
    default_gold = REPO_ROOT / "gold-test" / "data"
    default_result = REPO_ROOT / "gold-test" / "result"
    default_out = dpo_root / "output"

    parser = argparse.ArgumentParser(description="Build router DPO JSONL from gold-test CSVs.")
    parser.add_argument("--gold-data-dir", type=Path, default=default_gold)
    parser.add_argument("--result-dir", type=Path, default=default_result, help="gold-test result CSVs (optional)")
    parser.add_argument("--output-dir", type=Path, default=default_out)
    parser.add_argument(
        "--router-prompt-version",
        default="router-v2.00",
        help="Router prompt file id under app/prompts/",
    )
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--include-seed-faq", action="store_true", help="Include small-talk CSV (non-LLM in prod)")
    parser.add_argument("--include-hack", action="store_true", help="Include injection CSV (non-LLM in prod)")
    parser.add_argument(
        "--fetch-live",
        action="store_true",
        help="Call /v1/orchestrator/eval/router for rejected when result CSV missing or mismatch",
    )
    parser.add_argument(
        "--orchestrator-url",
        default="",
        help="Base URL for live eval (or set ORCHESTRATOR_URL)",
    )
    parser.add_argument("--fetch-timeout-s", type=float, default=60.0)
    args = parser.parse_args(argv)

    import os

    orch_url = (args.orchestrator_url or os.getenv("ORCHESTRATOR_URL") or "").strip()
    if args.fetch_live and not orch_url:
        print("error: --fetch-live requires --orchestrator-url or ORCHESTRATOR_URL", file=sys.stderr)
        return 1

    if not args.gold_data_dir.is_dir():
        print(f"error: gold data dir not found: {args.gold_data_dir}", file=sys.stderr)
        return 1

    system_prompt = _load_router_system_prompt(args.router_prompt_version)
    result_dir = args.result_dir if args.result_dir.is_dir() else None

    train, val, stats = build_dpo_dataset(
        gold_data_dir=args.gold_data_dir,
        result_dir=result_dir,
        system_prompt=system_prompt,
        include_seed_faq=args.include_seed_faq,
        include_hack=args.include_hack,
        fetch_live=args.fetch_live,
        orchestrator_url=orch_url,
        router_prompt_version=args.router_prompt_version,
        fetch_timeout_s=args.fetch_timeout_s,
        val_ratio=args.val_ratio,
    )

    out_dir = args.output_dir
    train_path = out_dir / "train.jsonl"
    val_path = out_dir / "val.jsonl"
    stats_path = out_dir / "build-stats.json"

    _write_jsonl(train_path, train)
    _write_jsonl(val_path, val)
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(train)} train -> {train_path}")
    print(f"wrote {len(val)} val   -> {val_path}")
    print(f"stats -> {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
