#!/usr/bin/env bash
# Batch router eval: read data/*.csv → result/<same-name>.csv (paths relative to this script).
set -euo pipefail

GOLD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$GOLD_ROOT/data}"
RESULT_DIR="${RESULT_DIR:-$GOLD_ROOT/result}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://192.168.86.179:30184}"
URL="${ORCHESTRATOR_URL%/}/orchestrator/eval/router"
CONCURRENCY="${CONCURRENCY:-4}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi

mkdir -p "$RESULT_DIR"

shopt -s nullglob
inputs=("$DATA_DIR"/*.csv)
shopt -u nullglob

if ((${#inputs[@]} == 0)); then
  echo "No CSV files found in $DATA_DIR" >&2
  exit 1
fi

process_one_csv() {
  local in_path="$1"
  local base out_path tmp_dir
  base="$(basename "$in_path" .csv)"
  out_path="$RESULT_DIR/${base}.csv"
  tmp_dir="$(mktemp -d)"

  local total
  total="$(awk '{ sub(/\r$/,""); if (NR>1 && index($0,",")>0) c++ } END { print c+0 }' "$in_path")"
  if ((total == 0)); then
    echo "Skip empty or header-only: $in_path" >&2
    rm -rf "$tmp_dir"
    return 0
  fi

  echo "→ $in_path ($total rows) → $out_path"

  local row running
  row=0
  running=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "${line//[$'\t\r\n ']/}" ]] && continue
    [[ "$line" == "question,expected_route" ]] && continue
    [[ "$line" != *,* ]] && continue
    local expected_route suffix question
    expected_route="${line##*,}"
    suffix=",$expected_route"
    question="${line%"$suffix"}"
    [[ -z "$question" || -z "$expected_route" ]] && continue
    row=$((row + 1))
    printf '%s\t%s\n' "$question" "$expected_route" >"$tmp_dir/meta$row"
    (
      http=$(curl -sS -o "$tmp_dir/body$row" -w "%{http_code}" -X POST "$URL" \
        -H "Content-Type: application/json" \
        -H "X-Request-Id: req-gold-${base}-$row" \
        -H "X-Session-Id: ses-gold" \
        -H "X-Trace-Id: trc-gold-${base}-$row" \
        -d "$(jq -n --arg q "$question" --arg r "$expected_route" \
          '{question: $q, expected_route: $r, router_prompt_version: "router-v1"}')")
      printf '%s' "$http" >"$tmp_dir/http$row"
    ) &
    running=$((running + 1))
    if ((running >= CONCURRENCY)); then
      while (($(jobs -rp | wc -l | tr -d ' ') >= CONCURRENCY)); do
        sleep 0.05
      done
      running=$(jobs -rp | wc -l | tr -d ' ')
    fi
  done <"$in_path"

  wait

  {
    echo "question,expected_route,actual_route,route_match"
    local i q er bodyf
    for ((i = 1; i <= row; i++)); do
      IFS=$'\t' read -r q er <"$tmp_dir/meta$i" || true
      bodyf="$tmp_dir/body$i"
      if [[ -s "$bodyf" ]] && jq -e . >/dev/null 2>&1 <"$bodyf"; then
        jq -r --arg q "$q" --arg er "$er" '
          (.decision // null) as $d
          | if $d != null then
            [
              $q,
              $er,
              ($d.route // ""),
              ((.evaluation // {}) | .route_match | if . == null then "null" elif . then "true" else "false" end)
            ] | @csv
          else
            [
              $q,
              $er,
              "",
              ""
            ] | @csv
          end
        ' <"$bodyf"
      else
        jq -n --arg q "$q" --arg er "$er" \
          '[$q, $er, "", ""] | @csv'
      fi
    done
  } >"$out_path"

  rm -rf "$tmp_dir"
}

for in_path in "${inputs[@]}"; do
  process_one_csv "$in_path"
done

echo "Done. CSV outputs in $RESULT_DIR/"
