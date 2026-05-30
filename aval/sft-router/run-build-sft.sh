#!/usr/bin/env bash
# Build router SFT JSONL from gold-test CSVs.
set -euo pipefail

SFT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVAL_ROOT="$(cd "$SFT_ROOT/.." && pwd)"
REPO_ROOT="$(cd "$AVAL_ROOT/.." && pwd)"
GOLD_DATA="${GOLD_DATA:-$AVAL_ROOT/gold-test/data}"
OUTPUT_DIR="${OUTPUT_DIR:-$SFT_ROOT/output}"
ROUTER_PROMPT_VERSION="${ROUTER_PROMPT_VERSION:-router-v2.00}"

ARGS=(
  --gold-data-dir "$GOLD_DATA"
  --output-dir "$OUTPUT_DIR"
  --router-prompt-version "$ROUTER_PROMPT_VERSION"
)

if [[ "${INCLUDE_SEED_FAQ:-0}" == "1" ]]; then
  ARGS+=(--include-seed-faq)
fi

if [[ "${INCLUDE_HACK:-0}" == "1" ]]; then
  ARGS+=(--include-hack)
fi

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" && -x "$REPO_ROOT/.venv/bin/python3" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python3"
fi
PYTHON="${PYTHON:-python3}"

exec "$PYTHON" "$SFT_ROOT/scripts/build_from_gold.py" "${ARGS[@]}" "$@"
