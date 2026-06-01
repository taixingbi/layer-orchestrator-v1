# Router eval report

- **Generated (UTC):** 2026-06-01T16:34:03Z
- **Orchestrator base:** `http://192.168.86.179:30184`
- **Eval endpoint:** `http://192.168.86.179:30184/v1/orchestrator/eval/router`
- **Concurrency:** 4
- **Router prompt version:** `router-v2.00` (`app/prompts/router-v2.00.txt`)

## Summary

| Metric | Count |
|--------|-------|
| Total rows | 77 |
| `route_match` = true | 77 |
| `route_match` = false | 0 |
| `route_match` = null | 0 |
| Other / short rows | 0 |
| **Match rate** (true / (true+false)) | **100.0%** |

## Per file

| File | Rows | true | false | null | other | Match rate |
|------|-----:|-----:|------:|-----:|------:|------------|
| `router_capabilities.csv` | 7 | 7 | 0 | 0 | 0 | 100.0% |
| `router_github.csv` | 4 | 4 | 0 | 0 | 0 | 100.0% |
| `router_greeting.csv` | 18 | 18 | 0 | 0 | 0 | 100.0% |
| `router_help.csv` | 5 | 5 | 0 | 0 | 0 | 100.0% |
| `router_identity.csv` | 7 | 7 | 0 | 0 | 0 | 100.0% |
| `router_rag_private_kb.csv` | 27 | 27 | 0 | 0 | 0 | 100.0% |
| `router_reject.csv` | 8 | 8 | 0 | 0 | 0 | 100.0% |
| `router_web_search.csv` | 1 | 1 | 0 | 0 | 0 | 100.0% |

## Bad items (`route_match` = false)

| Source file | expected_route | actual_route | question | rewritten_question | actual_answer |
|-------------|----------------|--------------|----------|--------------------|---------------|
| — | — | — | — | — | *none* |
