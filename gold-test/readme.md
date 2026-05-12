# Gold test (router eval)

Batch-evaluates the intent router: for each row in **`gold-test/data/*.csv`**, calls **`POST /orchestrator/eval/router`**, writes per-suite results under **`gold-test/result/`**, then builds **`result/router-eval-report-<ROUTER_PROMPT_VERSION>.md`** (for example **`result/router-eval-report-router-v1.00.md`** with the default prompt version).

## Requirements

- **bash**, **curl**, **jq** (request JSON + CSV escaping)
- **python3** (aggregate results + Markdown report)

## Layout

| Path | Role |
|------|------|
| **`data/*.csv`** | Gold inputs: header **`question,expected_route`**. The route is always the field after the **last** comma (questions may contain commas). |
| **`run-router-eval.sh`** | Runner; **`DATA_DIR`** / **`RESULT_DIR`** default next to this script (works from any cwd). |
| **`result/<name>.csv`** | One output per input basename, e.g. `data/router-gold-profile.csv` → `result/router-gold-profile.csv` (five columns: **`question`**, **`expected_route`**, **`actual_route`**, **`route_match`**, **`rewritten_question`**). |
| **`result/router-eval-report-<version>.md`** | Summary: counts, match rate, **`ROUTER_PROMPT_VERSION`**, **Bad items** (`route_match` = false). Filename includes the prompt id (e.g. **`router-eval-report-router-v1.00.md`**). |

## Run

```bash
bash gold-test/run-router-eval.sh
```

Use another prompt file under **`app/prompts/<version>.txt`**:

```bash
ROUTER_PROMPT_VERSION=router-v1.01 bash gold-test/run-router-eval.sh
```

On **stdout**, the script prints only a **`File` / `Match rate`** table (per result CSV plus an **`(all suites)`** row). **`router_prompt_version=…`** is printed on **stderr**. The full Markdown report is always written to **`REPORT_PATH`** (default **`result/router-eval-report-<ROUTER_PROMPT_VERSION>.md`**).

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_DIR` | `<gold-test>/data` | Input `*.csv` directory |
| `RESULT_DIR` | `<gold-test>/result` | Output directory |
| `ORCHESTRATOR_URL` | `http://192.168.86.179:30184` | Orchestrator base URL (no path) |
| `CONCURRENCY` | `4` | Parallel HTTP requests per file |
| `ROUTER_PROMPT_VERSION` | `router-v1.00` | JSON **`router_prompt_version`** on each eval request |
| `REPORT_PATH` | `<gold-test>/result/router-eval-report-<ROUTER_PROMPT_VERSION>.md` | Markdown report path (embeds prompt version unless overridden) |

## Input CSV

- **Header (required):** `question,expected_route`
- **`question`:** text before the final `,<expected_route>` suffix.

## Output CSV columns

`question`, `expected_route`, `actual_route`, `route_match`, `rewritten_question`

(`route_match` is from the eval API: **`true`** / **`false`** / **`null`** when no expected route was sent; gold rows always send **`expected_route`**, so you normally see booleans. **`rewritten_question`** comes from **`decision.rewritten_question`** on the eval response.)

## Suites

- **`data/router-gold-profile.csv`** — Candidate / profile–style questions (+ one **`direct_reply`** control).
- **`data/router-gold-mixed.csv`** — Profile, policy, immigration, and generic follow-ups.

## Report

After all CSVs are processed, the script scans **`result/*.csv`** files whose header starts with **`question,expected_route,actual_route,route_match`** (optional fifth column **`rewritten_question`**) and writes **`router-eval-report-<version>.md`** (or **`REPORT_PATH`**), including:

- UTC time, orchestrator URL, eval URL, concurrency, **`ROUTER_PROMPT_VERSION`**
- **Summary** and **Per file** tables (match rate = **`true / (true + false)`**)
- **Bad items**: every row where **`route_match`** is **`false`**, with **`rewritten_question`** when present in the result CSV

Generated **`result/*.csv`** and the report are listed in **`.gitignore`**; re-run the script to regenerate them.

## See also

- API shape: **`docs/schema-request-response.md`** (`POST /orchestrator/eval/router`)