# Gold test (router eval)

Batch-evaluates the intent router: for each row in **`aval/gold-test/data/**/*.csv`**, calls **`POST /v1/orchestrator/eval/router`**, writes per-suite results under **`aval/gold-test/result/`** (flat basename, e.g. `router_greeting.csv`), then builds **`result/router-eval-report-<ROUTER_PROMPT_VERSION>.md`**.

## Requirements

- **bash**, **curl**, **jq** (request JSON + CSV escaping)
- **python3** (aggregate results + Markdown report)

## Layout

| Path | Role |
|------|------|
| **`data/tools/*.csv`** | Tool-route gold (`rag_private_kb`, `web_search`, …). |
| **`data/internal/*.csv`** | Internal-intent gold (`greeting`, `identity`, `help`, …). |
| **Header** | **`question,expected_route`**. Every `question` is double-quoted; `expected_route` is unquoted. |
| **`run-router-eval.sh`** | Runner; **`DATA_DIR`** / **`RESULT_DIR`** default next to this script (works from any cwd). |
| **`result/<name>.csv`** | One output per input basename, e.g. `data/tools/router_rag_private_kb.csv` → `result/router_rag_private_kb.csv` (six columns: **`question`**, **`expected_route`**, **`actual_route`**, **`route_match`**, **`rewritten_question`**, **`actual_answer`**). |
| **`result/router-eval-report-<version>.md`** | Summary: counts, match rate, **`ROUTER_PROMPT_VERSION`**, **Bad items** (`route_match` = false). Filename includes the prompt id (e.g. **`router-eval-report-router-v1.00.md`**). |

## Run

```bash
bash aval/gold-test/run-router-eval.sh
```

Use another prompt file under **`app/prompts/<version>.txt`**:

```bash
CONCURRENCY=20 ROUTER_PROMPT_VERSION=router-v1.04 bash aval/gold-test/run-router-eval.sh
```

**Progress** (stderr) — one line per gold file, then the match-rate table on stdout:

```text
eval router-test-v1.04 · 8 files · http://192.168.86.179:30184
[1/8] router_capabilities 1/1
[2/8] router_greeting 3/3
[3/8] router_help 11/11
…
File                                             Match rate
router_greeting.csv                              66.7%
(all suites)                                     84.7%
```

Full Markdown report: **`result/router-eval-report-<ROUTER_PROMPT_VERSION>.md`**.

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `DATA_DIR` | `<aval/gold-test>/data` | Input `*.csv` directory |
| `RESULT_DIR` | `<aval/gold-test>/result` | Output directory |
| `ORCHESTRATOR_URL` | `http://192.168.86.179:30184` | Orchestrator base URL (no path) |
| `CONCURRENCY` | `4` | Parallel HTTP requests per file |
| `ROUTER_PROMPT_VERSION` | `router-v1.00` | JSON **`router_prompt_version`** on each eval request |
| `REPORT_PATH` | `<aval/gold-test>/result/router-eval-report-<ROUTER_PROMPT_VERSION>.md` | Markdown report path (embeds prompt version unless overridden) |

Eval responses now include `decision.route_detail` (nested) alongside legacy `decision.route`. Optional CSV columns for future suites: `expected_route_detail_type`, `expected_tool_name`.

## Input CSV

- **Header (required):** `question,expected_route`
- **`question`:** text before the final `,<expected_route>` suffix.

## Output CSV columns

`question`, `expected_route`, `actual_route`, `route_match`, `rewritten_question`, `actual_answer`

(`route_match` is from the eval API: **`true`** / **`false`** / **`null`** when no expected route was sent; gold rows always send **`expected_route`**, so you normally see booleans. **`rewritten_question`** comes from **`decision.rewritten_question`**. **`actual_answer`** is **`decision.answer`** from the eval response when **`actual_route`** is **`direct_reply`**; otherwise it is written as an empty field.)

## Suites

Filenames follow **`router_<suite>.csv`** (primary route or suite focus):

| File | Focus |
|------|--------|
| **`data/internal/router_greeting.csv`** | `greeting` — hi / how are you (smalltalk seed). |
| **`data/internal/router_identity.csv`** | `identity` — who are you / your name. |
| **`data/internal/router_capabilities.csv`** | `capabilities` — what can you do. |
| **`data/internal/router_help.csv`** | `help` — meta / off-topic assistant questions. |
| **`data/internal/router_reject.csv`** | Injection guard → **`reject`**. See [intent-router.md](../../docs/intent-router.md). |
| **`data/tools/router_rag_private_kb.csv`** | Candidate / profile (`rag_private_kb`). |
| **`data/tools/router_github.csv`** | HuntAI / layer repo architecture (`github_search`). |
| **`data/tools/router_web_search.csv`** | Public web / docs (`web_search`). |

## Small-talk seed (not RAG)

- **File:** [`app/prompts/seed_intents/*.json`](../app/prompts/seed_intents/*.json) — JSON array of `{ "intent", "user_examples", "answer" }`.
- **When:** Intent router runs with **empty** conversation history; the latest question is trimmed, lowercased, and internal whitespace collapsed, then compared **exactly** to each string in `user_examples` (same normalization).
- **Effect:** Returns **`direct_reply`** with the seed **`answer`** (no router LLM). Literal **`__CANDIDATE_NAME__`** in `answer` strings is replaced with the configured candidate name at runtime.

## Report

After all CSVs are processed, the script scans **`result/*.csv`** files whose header starts with **`question,expected_route,actual_route,route_match`** (optional fifth column **`rewritten_question`**, optional sixth **`actual_answer`**) and writes **`router-eval-report-<version>.md`** (or **`REPORT_PATH`**), including:

- UTC time, orchestrator URL, eval URL, concurrency, **`ROUTER_PROMPT_VERSION`**
- **Summary** and **Per file** tables (match rate = **`true / (true + false)`**)
- **Bad items**: every row where **`route_match`** is **`false`**, with **`rewritten_question`** and **`actual_answer`** when present in the result CSV

Generated **`result/*.csv`** and the report are listed in **`.gitignore`**; re-run the script to regenerate them.

## See also

- [aval/README.md](../README.md) — eval & dataset bundle overview
- API shape: **`docs/schema-request-response.md`** (`POST /v1/orchestrator/eval/router`)
- **Router DPO JSONL:** [`dpo-router/README.md`](../dpo-router/README.md) — preference pairs from these gold CSVs (+ eval results); **train** in [`layer-router-dpo-v1`](../../../layer-router-dpo-v1/README.md)
- **Router SFT JSONL:** [`sft-router/README.md`](../sft-router/README.md) — supervised chat examples (gold completions only)