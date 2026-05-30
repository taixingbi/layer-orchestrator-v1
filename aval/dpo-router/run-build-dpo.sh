#!/usr/bin/env bash
# Build router DPO JSONL from gold-test CSVs (and optional eval result CSVs).
set -euo pipefail

DPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AVAL_ROOT="$(cd "$DPO_ROOT/.." && pwd)"
REPO_ROOT="$(cd "$AVAL_ROOT/.." && pwd)"
GOLD_DATA="${GOLD_DATA:-$AVAL_ROOT/gold-test/data}"
GOLD_RESULT="${GOLD_RESULT:-$AVAL_ROOT/gold-test/result}"
OUTPUT_DIR="${OUTPUT_DIR:-$DPO_ROOT/output}"
ROUTER_PROMPT_VERSION="${ROUTER_PROMPT_VERSION:-router-v2.00}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-}"

ARGS=(
  --gold-data-dir "$GOLD_DATA"
  --output-dir "$OUTPUT_DIR"
  --router-prompt-version "$ROUTER_PROMPT_VERSION"
)

if [[ -d "$GOLD_RESULT" ]]; then
  ARGS+=(--result-dir "$GOLD_RESULT")
fi

if [[ "${FETCH_LIVE:-0}" == "1" ]]; then
  if [[ -z "$ORCHESTRATOR_URL" ]]; then
    echo "FETCH_LIVE=1 requires ORCHESTRATOR_URL" >&2
    exit 1
  fi
  ARGS+=(--fetch-live --orchestrator-url "$ORCHESTRATOR_URL")
fi

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

exec "$PYTHON" "$DPO_ROOT/scripts/build_from_gold.py" "${ARGS[@]}" "$@"
