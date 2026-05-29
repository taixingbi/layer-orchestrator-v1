#!/usr/bin/env bash
# Batch router eval: read data/**/*.csv → result/<basename>.csv (paths relative to this script).
set -euo pipefail

GOLD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-$GOLD_ROOT/data}"
RESULT_DIR="${RESULT_DIR:-$GOLD_ROOT/result}"
ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-http://192.168.86.179:30184}"
URL="${ORCHESTRATOR_URL%/}/v1/orchestrator/eval/router"
CONCURRENCY="${CONCURRENCY:-4}"
ROUTER_PROMPT_VERSION="${ROUTER_PROMPT_VERSION:-router-v2.00}"
REPORT_PATH="${REPORT_PATH:-$RESULT_DIR/router-eval-report-${ROUTER_PROMPT_VERSION}.md}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (for report generation)" >&2
  exit 1
fi

mkdir -p "$RESULT_DIR"

shopt -s nullglob globstar
inputs=("$DATA_DIR"/*.csv "$DATA_DIR"/*/*.csv)
shopt -u nullglob globstar

if ((${#inputs[@]} == 0)); then
  echo "No CSV files found under $DATA_DIR (expected data/*.csv or data/*/*.csv)" >&2
  exit 1
fi

echo "eval ${ROUTER_PROMPT_VERSION} · ${#inputs[@]} files · ${ORCHESTRATOR_URL}" >&2

process_one_csv() {
  local in_path="$1"
  local file_idx="$2"
  local file_total="$3"
  local base out_path tmp_dir
  base="$(basename "$in_path" .csv)"
  out_path="$RESULT_DIR/${base}.csv"
  tmp_dir="$(mktemp -d)"

  local total
  total="$(python3 - "$in_path" <<'PY'
import csv, sys
path = sys.argv[1]
with open(path, newline="", encoding="utf-8") as f:
    n = sum(
        1
        for row in csv.DictReader(f)
        if (row.get("question") or "").strip() and (row.get("expected_route") or "").strip()
    )
print(n)
PY
)"
  if ((total == 0)); then
    echo "[$file_idx/$file_total] $base skip (empty)" >&2
    rm -rf "$tmp_dir"
    return 0
  fi

  local row running
  row=0
  running=0
  while IFS=$'\t' read -r question expected_route || [[ -n "$question" ]]; do
    [[ -z "$question" || -z "$expected_route" ]] && continue
    row=$((row + 1))
    printf '%s\t%s\n' "$question" "$expected_route" >"$tmp_dir/meta$row"
    local row_num="$row"
    (
      http=$(curl -sS -o "$tmp_dir/body$row_num" -w "%{http_code}" -X POST "$URL" \
        -H "Content-Type: application/json" \
        -H "X-Request-Id: req-gold-${base}-$row_num" \
        -H "X-Session-Id: ses-gold" \
        -H "X-Trace-Id: trc-gold-${base}-$row_num" \
        -d "$(jq -n --arg q "$question" --arg r "$expected_route" --arg pv "$ROUTER_PROMPT_VERSION" \
          '{question: $q, expected_route: $r, router_prompt_version: $pv}')")
      printf '%s' "$http" >"$tmp_dir/http$row_num"
    ) &
    running=$((running + 1))
    if ((running >= CONCURRENCY)); then
      while (($(jobs -rp | wc -l | tr -d ' ') >= CONCURRENCY)); do
        sleep 0.05
      done
      running=$(jobs -rp | wc -l | tr -d ' ')
    fi
  done < <(python3 - "$in_path" <<'PY'
import csv, sys
path = sys.argv[1]
with open(path, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        q = (row.get("question") or "").strip()
        er = (row.get("expected_route") or "").strip()
        if q and er:
            print(f"{q}\t{er}")
PY
)

  wait

  {
    echo "question,expected_route,actual_route,route_match,rewritten_question,actual_answer"
    local i q er bodyf
    for ((i = 1; i <= row; i++)); do
      IFS=$'\t' read -r q er <"$tmp_dir/meta$i" || true
      bodyf="$tmp_dir/body$i"
      if [[ -s "$bodyf" ]] && jq -e . >/dev/null 2>&1 <"$bodyf"; then
        jq -r --arg q "$q" --arg er "$er" '
          (.decision // null) as $d
          | if $d != null then
              (
                if ($d.route // "") == "direct_reply" then ($d.answer // "")
                else ""
                end
              ) as $aa
              | [
                  $q,
                  $er,
                  ($d.route // ""),
                  ((.evaluation // {}) | .route_match | if . == null then "null" elif . then "true" else "false" end),
                  ($d.rewritten_question // ""),
                  $aa
                ] | @csv
          else
            [
              $q,
              $er,
              "",
              "",
              "",
              ""
            ] | @csv
          end
        ' <"$bodyf"
      else
        jq -n --arg q "$q" --arg er "$er" \
          '[$q, $er, "", "", "", ""] | @csv'
      fi
    done
  } >"$out_path"

  echo "[$file_idx/$file_total] $base $row/$row" >&2

  rm -rf "$tmp_dir"
}

generate_report() {
  local generated_at
  generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  python3 - "$REPORT_PATH" "$RESULT_DIR" "$URL" "$ORCHESTRATOR_URL" "$CONCURRENCY" "$generated_at" "$ROUTER_PROMPT_VERSION" <<'PY'
import csv, glob, os, sys

report_path, result_dir, eval_url, orch_base, conc, ts, prompt_ver = sys.argv[1:8]

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
        norm = [x.strip().lstrip("\ufeff") for x in header]
        want = ["question", "expected_route", "actual_route", "route_match"]
        if norm[:4] != want:
            continue
        has_rw = len(norm) >= 5 and norm[4] == "rewritten_question"
        has_aa = len(norm) >= 6 and norm[5] == "actual_answer"
        for row in r:
            if len(row) < 4:
                c["other"] += 1
                tot["other"] += 1
                continue
            c["rows"] += 1
            tot["rows"] += 1
            q, er, ar, rm = row[0], row[1], row[2], row[3]
            rw = row[4] if has_rw and len(row) > 4 else ""
            aa = row[5] if has_aa and len(row) > 5 else ""
            m = (rm or "").strip().lower()
            if m == "true":
                c["true"] += 1
                tot["true"] += 1
            elif m == "false":
                c["false"] += 1
                tot["false"] += 1
                bad_items.append((name, q, er, ar, rw, aa))
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
    f"- **Router prompt version:** `{prompt_ver}` (`app/prompts/{prompt_ver}.txt`)",
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
lines.append("| Source file | expected_route | actual_route | question | rewritten_question | actual_answer |")
lines.append("|-------------|----------------|--------------|----------|--------------------|---------------|")
if bad_items:
    for name, q, er, ar, rw, aa in sorted(bad_items, key=lambda x: (x[0], x[1] or "")):
        lines.append(
            f"| `{esc_cell(name)}` | {esc_cell(er)} | {esc_cell(ar)} | {esc_cell(q)} | {esc_cell(rw, max_len=220)} | {esc_cell(aa, max_len=220)} |"
        )
else:
    lines.append("| — | — | — | — | — | *none* |")
lines.append("")

os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)
with open(report_path, "w", encoding="utf-8") as out:
    out.write("\n".join(lines))

# stdout: File + Match rate only (terminal summary)
col_w = 48
print(f"{'File':<{col_w}} Match rate", flush=True)
for name, c in per_file:
    print(f"{name:<{col_w}} {rate(c['true'], c['false'])}", flush=True)
print(f"{'(all suites)':<{col_w}} {rate(tot['true'], tot['false'])}", flush=True)
PY
}

file_idx=0
file_total=${#inputs[@]}
for in_path in "${inputs[@]}"; do
  file_idx=$((file_idx + 1))
  process_one_csv "$in_path" "$file_idx" "$file_total"
done

generate_report
