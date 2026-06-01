#!/usr/bin/env python3
"""Build router SFT JSONL from gold-test CSVs (gold completions only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROUTER_EVAL_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ROUTER_EVAL_ROOT.parent
DPO_SCRIPTS = ROUTER_EVAL_ROOT / "dpo-router" / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(DPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DPO_SCRIPTS))

from router_gold import (  # noqa: E402
    GoldRow,
    build_router_completion,
    build_user_message,
    canonical_expected_route,
    completion_json,
    iter_gold_rows,
    load_router_system_prompt,
    router_llm_eligible,
    val_split,
    write_jsonl,
)


def _sft_record(
    *,
    system_prompt: str,
    row: GoldRow,
    completion: Dict[str, Any],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_message(row)},
            {"role": "assistant", "content": completion_json(completion)},
        ],
        "meta": meta,
    }


def build_sft_dataset(
    *,
    gold_data_dir: Path,
    system_prompt: str,
    include_seed_faq: bool,
    include_hack: bool,
    router_prompt_version: str,
    val_ratio: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    train: List[Dict[str, Any]] = []
    val: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {
        "rows_total": 0,
        "examples_written": 0,
        "skipped_ineligible": 0,
        "by_expected_route": {},
        "completion_source": {"gold": 0},
    }

    for row in iter_gold_rows(
        gold_data_dir,
        include_seed_faq=include_seed_faq,
        include_hack=include_hack,
    ):
        stats["rows_total"] += 1
        canonical = canonical_expected_route(row)
        stats["by_expected_route"][canonical] = stats["by_expected_route"].get(canonical, 0) + 1

        if not router_llm_eligible(row):
            stats["skipped_ineligible"] += 1
            continue

        completion = build_router_completion(row, label="gold")
        meta = {
            "question": row.question,
            "expected_route": canonical,
            "source_file": row.source_file,
            "completion_source": "gold",
            "router_prompt_version": router_prompt_version,
        }
        record = _sft_record(
            system_prompt=system_prompt,
            row=row,
            completion=completion,
            meta=meta,
        )
        stats["examples_written"] += 1
        stats["completion_source"]["gold"] += 1
        if val_split(row.question, val_ratio):
            val.append(record)
        else:
            train.append(record)

    return train, val, stats


def main(argv: Optional[Sequence[str]] = None) -> int:
    sft_root = Path(__file__).resolve().parents[1]
    default_gold = ROUTER_EVAL_ROOT / "gold-test" / "data"
    default_out = sft_root / "output"

    parser = argparse.ArgumentParser(description="Build router SFT JSONL from gold-test CSVs.")
    parser.add_argument("--gold-data-dir", type=Path, default=default_gold)
    parser.add_argument("--output-dir", type=Path, default=default_out)
    parser.add_argument(
        "--router-prompt-version",
        default="router-v2.00",
        help="Router prompt file id under app/prompts/",
    )
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--include-seed-faq", action="store_true", help="Include small-talk CSV (non-LLM in prod)")
    parser.add_argument("--include-hack", action="store_true", help="Include injection CSV (non-LLM in prod)")
    args = parser.parse_args(argv)

    if not args.gold_data_dir.is_dir():
        print(f"error: gold data dir not found: {args.gold_data_dir}", file=sys.stderr)
        return 1

    system_prompt = load_router_system_prompt(args.router_prompt_version)
    train, val, stats = build_sft_dataset(
        gold_data_dir=args.gold_data_dir,
        system_prompt=system_prompt,
        include_seed_faq=args.include_seed_faq,
        include_hack=args.include_hack,
        router_prompt_version=args.router_prompt_version,
        val_ratio=args.val_ratio,
    )

    out_dir = args.output_dir
    train_path = out_dir / "train.jsonl"
    val_path = out_dir / "val.jsonl"
    stats_path = out_dir / "build-stats.json"

    write_jsonl(train_path, train)
    write_jsonl(val_path, val)
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {len(train)} train -> {train_path}")
    print(f"wrote {len(val)} val   -> {val_path}")
    print(f"stats -> {stats_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
