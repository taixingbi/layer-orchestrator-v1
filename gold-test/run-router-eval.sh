#!/usr/bin/env bash
# Batch router eval: read data/*.csv → result/<same-name>.csv (paths relative to this script).
set -euo pipefail

GOLD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$GOLD_ROOT/data}"
RESULT_DIR="${RESULT_DIR:-$GOLD_ROOT/result}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://192.168.86.179:30184}"
URL="${ORCHESTRATOR_URL%/}/orchestrator/eval/router"
CONCURRENCY="${CONCURRENCY:-4}"
REPORT_PATH="${REPORT_PATH:-$RESULT_DIR/router-eval-report.md}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (for report generation)" >&2
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

generate_report() {
  local generated_at
  generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  python3 - "$REPORT_PATH" "$RESULT_DIR" "$URL" "$ORCHESTRATOR_URL" "$CONCURRENCY" "$generated_at" <<'PY'
import csv, glob, os, sys

report_path, result_dir, eval_url, orch_base, conc, ts = sys.argv[1:7]

per_file = []
tot = {"rows": 0, "true": 0, "false": 0, "null": 0, "other": 0}
bad_items = []

for path in sorted(glob.glob(os.path.join(result_dir, "*.csv"))):
    name = os.path.basename(path)
    c = {"rows": 0, "true": 0, "false": 0, "null": 0, "other": 0}
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        header = next(r, None)
        if not header:
            continue
        norm = [x.strip().lstrip("\ufeff") for x in header[:4]]
        if norm != ["question", "expected_route", "actual_route", "route_match"]:
            continue
        for row in r:
            if len(row) < 4:
                c["other"] += 1
                tot["other"] += 1
                continue
            c["rows"] += 1
            tot["rows"] += 1
            q, er, ar, rm = row[0], row[1], row[2], row[3]
            m = (rm or "").strip().lower()
            if m == "true":
                c["true"] += 1
                tot["true"] += 1
            elif m == "false":
                c["false"] += 1
                tot["false"] += 1
                bad_items.append((name, q, er, ar, rm))
            elif m == "null":
                c["null"] += 1
                tot["null"] += 1
            else:
                c["other"] += 1
                tot["other"] += 1
    per_file.append((name, c))


def rate(t, f):
    d = t + f
    return f"{100.0 * t / d:.1f}%" if d else "n/a"


def esc_cell(s, max_len=180):
    if s is None:
        return ""
    t = str(s).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    return (t[:max_len] + "…") if len(t) > max_len else t


lines = [
    "# Router eval report",
    "",
    f"- **Generated (UTC):** {ts}",
    f"- **Orchestrator base:** `{orch_base}`",
    f"- **Eval endpoint:** `{eval_url}`",
    f"- **Concurrency:** {conc}",
    "",
    "## Summary",
    "",
    "| Metric | Count |",
    "|--------|-------|",
    f"| Total rows | {tot['rows']} |",
    f"| `route_match` = true | {tot['true']} |",
    f"| `route_match` = false | {tot['false']} |",
    f"| `route_match` = null | {tot['null']} |",
    f"| Other / short rows | {tot['other']} |",
    f"| **Match rate** (true / (true+false)) | **{rate(tot['true'], tot['false'])}** |",
    "",
    "## Per file",
    "",
    "| File | Rows | true | false | null | other | Match rate |",
    "|------|-----:|-----:|------:|-----:|------:|------------|",
]
for name, c in per_file:
    lines.append(
        f"| `{name}` | {c['rows']} | {c['true']} | {c['false']} | {c['null']} | {c['other']} | {rate(c['true'], c['false'])} |"
    )
lines.append("")
lines.append("## Bad items (`route_match` = false)")
lines.append("")
lines.append("| Source file | expected_route | actual_route | question |")
lines.append("|-------------|----------------|--------------|----------|")
if bad_items:
    for name, q, er, ar, rm in sorted(bad_items, key=lambda x: (x[0], x[1] or "")):
        lines.append(
            f"| `{esc_cell(name)}` | {esc_cell(er)} | {esc_cell(ar)} | {esc_cell(q)} |"
        )
else:
    lines.append("| — | — | — | *none* |")
lines.append("")

os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
with open(report_path, "w", encoding="utf-8") as out:
    out.write("\n".join(lines))
print(report_path, flush=True)
PY
}

for in_path in "${inputs[@]}"; do
  process_one_csv "$in_path"
done

generate_report
echo "Done. CSV outputs in $RESULT_DIR/"
echo "Report: $REPORT_PATH"
