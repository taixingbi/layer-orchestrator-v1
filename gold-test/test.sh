#!/usr/bin/env bash
set -euo pipefail

INPUT_FILE="${1:-gold-test/test1.txt}"
OUTPUT_FILE="gold-test/result"
URL="http://192.168.86.179:30183/v1/rag/query"
CONCURRENCY="${CONCURRENCY:-4}"

: > "$OUTPUT_FILE"

if [[ ! -f "$INPUT_FILE" ]]; then
  echo "Input file not found: $INPUT_FILE" >&2
  exit 1
fi

export URL
TOTAL="$(awk 'NF { c++ } END { print c + 0 }' "$INPUT_FILE")"

if (( TOTAL == 0 )); then
  echo "No non-empty questions found in $INPUT_FILE" >&2
  exit 1
fi

echo "Running $TOTAL questions with concurrency=$CONCURRENCY"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

worker() {
  idx="$1"
  question="$2"
  out_file="$tmp_dir/q$idx"
  raw="$tmp_dir/raw$idx"
  printf '[%s/%s] start: %s\n' "$idx" "$TOTAL" "$question"
  curl -sS -X POST "$URL" \
    -H "Content-Type: application/json" \
    -H "X-Request-Id: req-abc123-$idx" \
    -H "X-Session-Id: ses-xyz789" \
    -H "X-Trace-Id: trc-001-$idx" \
    -H "X-User-Roles: hr" \
    -d "$(jq -n --arg q "$question" '{question: $q, collection_base: "taixing_knowledge", k: 5, k_max: 40}')" \
    > "$raw"
  if jq . "$raw" >/dev/null 2>&1; then
    jq . "$raw" > "$out_file"
  else
    {
      echo '{"error":"non_json_response","raw":'
      jq -Rs . < "$raw"
      echo '}'
    } > "$out_file"
  fi
  printf '[%s/%s] done\n' "$idx" "$TOTAL"
}

idx=0
running=0
while IFS= read -r question || [[ -n "$question" ]]; do
  [[ -z "$question" ]] && continue
  idx=$((idx + 1))
  worker "$idx" "$question" &
  running=$((running + 1))
  if (( running >= CONCURRENCY )); then
    while (( "$(jobs -rp | wc -l | tr -d ' ')" >= CONCURRENCY )); do
      sleep 0.05
    done
    running="$(jobs -rp | wc -l | tr -d ' ')"
  fi
done < "$INPUT_FILE"

wait

idx=0
while IFS= read -r question || [[ -n "$question" ]]; do
  [[ -z "$question" ]] && continue
  idx=$((idx + 1))
  echo "Q: $question" >> "$OUTPUT_FILE"
  cat "$tmp_dir/q$idx" >> "$OUTPUT_FILE"
  echo >> "$OUTPUT_FILE"
done < "$INPUT_FILE"