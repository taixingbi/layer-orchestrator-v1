# Router SFT dataset (`sft-router`)

Build **supervised fine-tuning (SFT)** JSONL for the **intent router LLM only** (`run_intent_rewrite_router` in `app/core/intent_router.py`). Same gold sources and eligibility rules as [`dpo-router`](../dpo-router/README.md), but **gold completions only** (no rejected pairs).

## Layout

| Path | Role |
|------|------|
| `scripts/build_from_gold.py` | Read `gold-test/data/**/*.csv` → `output/train.jsonl`, `output/val.jsonl` |
| `run-build-sft.sh` | Wrapper with env defaults |
| `output/` | Generated JSONL (`train.jsonl`, `val.jsonl`, `build-stats.json`) — committed for training |

Shared gold logic lives in [`dpo-router/scripts/router_gold.py`](../dpo-router/scripts/router_gold.py).

## Quick start

```bash
bash aval/sft-router/run-build-sft.sh
```

## JSONL record shape

Each line is a chat conversation ending with the router JSON completion:

```json
{
  "messages": [
    {"role": "system", "content": "<app/prompts/router-v2.00.txt rendered>"},
    {"role": "user", "content": "History:\n(none)\n\nLatest question:\n..."},
    {"role": "assistant", "content": "{\"rewritten_question\":\"...\",\"route\":\"rag_private_kb\",...}"}
  ],
  "meta": {
    "question": "...",
    "expected_route": "rag_private_kb",
    "source_file": "router_rag_private_kb.csv",
    "completion_source": "gold",
    "router_prompt_version": "router-v2.00"
  }
}
```

Assistant JSON matches DPO **`chosen`** (same `build_router_completion` helper).

## Default exclusions (same as DPO)

Skips internal seed CSVs, injection guard, deterministic `github_search`, `reject`, and `clarify` — see `router_llm_eligible` in `router_gold.py`.

Include with:

```bash
INCLUDE_SEED_FAQ=1 INCLUDE_HACK=1 bash aval/sft-router/run-build-sft.sh
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `GOLD_DATA` | `../gold-test/data` | Input CSV directory |
| `OUTPUT_DIR` | `aval/sft-router/output` | Output JSONL directory |
| `ROUTER_PROMPT_VERSION` | `router-v2.00` | Prompt file under `app/prompts/` |
| `INCLUDE_SEED_FAQ` | `0` | Include greeting/identity/help/capabilities gold |
| `INCLUDE_HACK` | `0` | Include injection gold |

Train/val split uses the same hash on `question` as DPO (`val_ratio=0.1`).

## See also

- [aval/README.md](../README.md) — eval & dataset bundle overview
- [dpo-router/README.md](../dpo-router/README.md) — preference pairs (DPO)
- [gold-test/readme.md](../gold-test/readme.md) — gold CSV format
- [layer-router-dpo-v1](../../../layer-router-dpo-v1/README.md) — QLoRA DPO training (optional SFT trainer can consume this output similarly)
