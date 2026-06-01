# Router eval report

- **Generated (UTC):** 2026-06-01T15:17:18Z
- **Orchestrator base:** `http://192.168.86.179:30184`
- **Eval endpoint:** `http://192.168.86.179:30184/v1/orchestrator/eval/router`
- **Concurrency:** 4
- **Router prompt version:** `router-v2.00` (`app/prompts/router-v2.00.txt`)

## Summary

| Metric | Count |
|--------|-------|
| Total rows | 77 |
| `route_match` = true | 76 |
| `route_match` = false | 1 |
| `route_match` = null | 0 |
| Other / short rows | 0 |
| **Match rate** (true / (true+false)) | **98.7%** |

## Per file

| File | Rows | true | false | null | other | Match rate |
|------|-----:|-----:|------:|-----:|------:|------------|
| `router_capabilities.csv` | 7 | 7 | 0 | 0 | 0 | 100.0% |
| `router_github.csv` | 4 | 4 | 0 | 0 | 0 | 100.0% |
| `router_greeting.csv` | 18 | 17 | 1 | 0 | 0 | 94.4% |
| `router_help.csv` | 5 | 5 | 0 | 0 | 0 | 100.0% |
| `router_identity.csv` | 7 | 7 | 0 | 0 | 0 | 100.0% |
| `router_rag_private_kb.csv` | 27 | 27 | 0 | 0 | 0 | 100.0% |
| `router_reject.csv` | 8 | 8 | 0 | 0 | 0 | 100.0% |
| `router_web_search.csv` | 1 | 1 | 0 | 0 | 0 | 100.0% |

## Bad items (`route_match` = false)

| Source file | expected_route | actual_route | question | rewritten_question | actual_answer |
|-------------|----------------|--------------|----------|--------------------|---------------|
| `router_greeting.csv` | greeting | help | Tell me a funny story? | Tell me a funny story? |  |
