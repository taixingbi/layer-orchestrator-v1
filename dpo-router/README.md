# Router DPO dataset (`dpo-router`)

Build **Direct Preference Optimization (DPO)** JSONL for the **intent router LLM only** (`run_intent_rewrite_router` in `app/core/intent_router.py`). This does not train RAG, GitHub MCP, or answer models.

Same layout level as [`gold-test/`](../gold-test/README.md): gold labels in, preference pairs out.

## Layout

| Path | Role |
|------|------|
| `scripts/build_from_gold.py` | Read `gold-test/data/**/*.csv` → `output/train.jsonl`, `output/val.jsonl` |
| `run-build-dpo.sh` | Wrapper with env defaults |
| `output/` | Generated JSONL (gitignored) |

## Quick start

From repo root (uses gold CSVs; synthetic **rejected** if no eval results):

```bash
bash dpo-router/run-build-dpo.sh
```

After running [`gold-test/run-router-eval.sh`](../gold-test/run-router-eval.sh), rebuild so **rejected** comes from real mismatches in `gold-test/result/*.csv`:

```bash
ROUTER_PROMPT_VERSION=router-v2.00 bash gold-test/run-router-eval.sh
bash dpo-router/run-build-dpo.sh
```

Live eval for rejected (no result CSV needed):

```bash
ORCHESTRATOR_URL=http://127.0.0.1:8000 FETCH_LIVE=1 bash dpo-router/run-build-dpo.sh
```

## JSONL record shape

Each line matches what the router LLM sees in production:

```json
{
  "prompt": [
    {"role": "system", "content": "<app/prompts/router-v2.00.txt rendered>"},
    {"role": "user", "content": "History:\n(none)\n\nLatest question:\n..."}
  ],
  "chosen": "{\"rewritten_question\":\"...\",\"route_detail\":{...},\"route\":\"tool\",...}",
  "rejected": "{\"rewritten_question\":\"...\",\"route_detail\":{...},\"route\":\"direct_reply\",...}",
  "meta": {
    "question": "...",
    "expected_route": "rag",
    "source_file": "router_rag_private_kb.csv",
    "rejected_source": "result_csv | live_eval | synthetic",
    "router_prompt_version": "router-v2.00"
  }
}
```

- **chosen** — built from gold `expected_route` (`rag` → `tool` + `rag_private_kb`, etc.)
- **rejected** — eval mismatch from result CSV, live `/v1/orchestrator/eval/router`, or synthetic opposite route

## Gold CSV mapping

| `expected_route` | Chosen `route` | Chosen `route_detail.name` |
|------------------|----------------|----------------------------|
| `rag` | `tool` | `rag_private_kb` |
| `tool` | `tool` | `expected_tool` column or `github_search` |
| `direct_reply` | `direct_reply` | `greeting` / `identity` / `capabilities` / `help` (heuristic) |
| `clarify` | `clarify` | `clarify` |
| `reject` | `reject` | `reject` |

Optional CSV columns (future): `expected_tool`, `history_json` (array of `{role, content}`).

## Default exclusions (LLM-free paths in prod)

By default **skips**:

- `internal/router_*.csv` (greeting, identity, help, capabilities) — small-talk seed (no router LLM)
- `router_reject.csv` — injection guard (no router LLM)

Include with:

```bash
INCLUDE_SEED_FAQ=1 INCLUDE_HACK=1 bash dpo-router/run-build-dpo.sh
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `GOLD_DATA` | `../gold-test/data` | Input CSV directory |
| `GOLD_RESULT` | `../gold-test/result` | Eval result CSVs (optional) |
| `OUTPUT_DIR` | `dpo-router/output` | Output JSONL directory |
| `ROUTER_PROMPT_VERSION` | `router-v2.00` | Prompt file under `app/prompts/` |
| `FETCH_LIVE` | `0` | Set `1` to call eval API for rejected |
| `ORCHESTRATOR_URL` | — | Required when `FETCH_LIVE=1` |
| `INCLUDE_SEED_FAQ` | `0` | Include seed-FAQ gold file |
| `INCLUDE_HACK` | `0` | Include hack gold file |

## Training (outside this repo)

Use [TRL `DPOTrainer`](https://huggingface.co/docs/trl/dpo_trainer) or your gateway fine-tune pipeline:

1. Base model = same family as `LLM_MODEL` / router gateway model.
2. Train on `output/train.jsonl` (validate on `output/val.jsonl`).
3. Deploy fine-tuned weights; set router model on gateway / `router_model` on eval.

Post-train, re-run gold eval:

```bash
ROUTER_PROMPT_VERSION=router-v2.00 bash gold-test/run-router-eval.sh
```

## See also

- [intent-router.md](../docs/intent-router.md) — router execution order
- [schema-request-response.md](../docs/schema/schema-request-response.md) — `POST /v1/orchestrator/eval/router`
- [gold-test/readme.md](../gold-test/readme.md) — gold CSV format
