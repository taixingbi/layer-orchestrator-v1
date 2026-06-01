# Router evaluation & training data (`router-eval`)

Gold router eval harness and dataset builders for intent-router LLM training.

| Path | Role |
|------|------|
| [`golden-test/`](golden-test/readme.md) | Batch eval against `POST /v1/orchestrator/eval/router` |
| [`dpo-router/`](dpo-router/README.md) | DPO preference JSONL from gold (+ optional eval mismatches) |
| [`sft-router/`](sft-router/README.md) | SFT chat JSONL from gold completions only |

## Quick start

From `layer-orchestrator-v1` repo root:

```bash
# 1) Eval router against gold CSVs
bash router-eval/golden-test/run-router-eval.sh

# 2) Build DPO dataset (uses result CSVs when present)
bash router-eval/dpo-router/run-build-dpo.sh

# 3) Build SFT dataset
bash router-eval/sft-router/run-build-sft.sh
```

Train SFT/DPO in sibling app [`layer-router-train-v1`](../../layer-router-train-v1/README.md) (fetches `router-eval/{dpo,sft}-router/output/*.jsonl` from GitHub or monorepo path).

## See also

- [Router routes & gold suites](../docs/router.md)
- [Intent router](../docs/intent-router.md)
