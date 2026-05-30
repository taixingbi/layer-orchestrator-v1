# Router evaluation & training data (`aval`)

Gold router eval harness and dataset builders for intent-router LLM training.

| Path | Role |
|------|------|
| [`gold-test/`](gold-test/readme.md) | Batch eval against `POST /v1/orchestrator/eval/router` |
| [`dpo-router/`](dpo-router/README.md) | DPO preference JSONL from gold (+ optional eval mismatches) |
| [`sft-router/`](sft-router/README.md) | SFT chat JSONL from gold completions only |

## Quick start

From `layer-orchestrator-v1` repo root:

```bash
# 1) Eval router against gold CSVs
bash aval/gold-test/run-router-eval.sh

# 2) Build DPO dataset (uses result CSVs when present)
bash aval/dpo-router/run-build-dpo.sh

# 3) Build SFT dataset
bash aval/sft-router/run-build-sft.sh
```

Train DPO in sibling app [`layer-router-dpo-v1`](../../layer-router-dpo-v1/README.md) (fetches `aval/dpo-router/output/*.jsonl` from GitHub or monorepo path).

## See also

- [Router routes & gold suites](../docs/router.md)
- [Intent router](../docs/intent-router.md)
