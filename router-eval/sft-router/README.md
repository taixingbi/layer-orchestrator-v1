# Router SFT dataset (`sft-router`)

Build **supervised fine-tuning (SFT)** JSONL for the **intent router LLM only** (`run_intent_rewrite_router` in `app/core/intent_router.py`). Same gold sources and eligibility rules as [`dpo-router`](../dpo-router/README.md), but **gold completions only** (no rejected pairs).

## Layout

| Path | Role |
|------|------|
| `scripts/build_from_gold.py` | Read `golden-test/data/**/*.csv` → `output/train.jsonl`, `output/val.jsonl` |
| `run-build-sft.sh` | Wrapper with env defaults |
| `output/` | Generated JSONL (`train.jsonl`, `val.jsonl`, `build-stats.json`) — committed for training |

Shared gold logic lives in [`dpo-router/scripts/router_gold.py`](../dpo-router/scripts/router_gold.py).

## Quick start

```bash
bash router-eval/sft-router/run-build-sft.sh
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
INCLUDE_SEED_FAQ=1 INCLUDE_HACK=1 bash router-eval/sft-router/run-build-sft.sh
```

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `GOLD_DATA` | `../golden-test/data` | Input CSV directory |
| `OUTPUT_DIR` | `router-eval/sft-router/output` | Output JSONL directory |
| `ROUTER_PROMPT_VERSION` | `router-v2.00` | Prompt file under `app/prompts/` |
| `INCLUDE_SEED_FAQ` | `0` | Include greeting/identity/help/capabilities gold |
| `INCLUDE_HACK` | `0` | Include injection gold |

Train/val split uses the same hash on `question` as DPO (`val_ratio=0.1`).

## Test trained adapter (single-request smoke)

After training in [layer-router-train-v1](../../../layer-router-train-v1/README.md) and loading LoRAs on vLLM (`router-qwen2.5-7b-sft-v1.00`, `router-qwen2.5-7b-dpo-v1.00` — see [deploy-vllm-inference.md](../../../huntai-k3s/docs/deploy-vllm-inference.md)), call `POST /v1/orchestrator/eval/router` with **`router_model`** set to the vLLM LoRA id. Use the same **`router_prompt_version`** you trained on (e.g. `router-v2.00`). Check `evaluation.route_match`, `decision.route`, and `router.model`.

Orchestrator base URL (adjust if needed): `http://192.168.86.179:30184`.

**SFT adapter:**

```bash
curl -sS -X POST "http://192.168.86.179:30184/v1/orchestrator/eval/router" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the renewal requirements for H4 EAD?",
    "expected_route": "rag",
    "router_model": "router-qwen2.5-7b-sft-v1.00",
    "router_prompt_version": "router-v2.00",
    "router_temperature": 0
  }' | jq '.evaluation, .decision.route, .router.model'
```

**DPO adapter:**

```bash
curl -sS -X POST "http://192.168.86.179:30184/v1/orchestrator/eval/router" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the renewal requirements for H4 EAD?",
    "expected_route": "rag",
    "router_model": "router-qwen2.5-7b-dpo-v1.00",
    "router_prompt_version": "router-v2.00",
    "router_temperature": 0
  }' | jq '.evaluation, .decision.route, .router.model'
```

Full gold-suite batch eval: [golden-test/readme.md](../golden-test/readme.md). Pass the LoRA id via **`ROUTER_MODEL`** on the script (or set orchestrator **`ROUTER_MODEL`** / **`LLM_MODEL`** env):

```bash
ROUTER_MODEL=router-qwen2.5-7b-sft-v1.00 \
RESULT_DIR=router-eval/golden-test/result/sft-v1.00 \
  bash router-eval/golden-test/run-router-eval.sh
```

## See also

- [router-eval/README.md](../README.md) — eval & dataset bundle overview
- [dpo-router/README.md](../dpo-router/README.md) — preference pairs (DPO)
- [golden-test/readme.md](../golden-test/readme.md) — gold CSV format
- [layer-router-train-v1](../../../layer-router-train-v1/README.md) — QLoRA SFT / DPO training (`TRAIN_METHOD=sft` uses this JSONL)
