# System Design

This document explains the runtime design of `layer-orchestrator-v1`: components, request flows, reliability loops, and key trade-offs.

## Goals

- Provide a single API for question answering over Taixing-focused knowledge.
- Keep responses observable (SSE events + structured logs).
- Prefer grounded answers (RAG retrieval text returned as the user-visible answer when `route` is `rag`; no separate answer synthesis LLM in the graph).
- Keep integration simple with OpenAI-compatible inference gateways.

## Runtime Components

- `app/main.py`  
  FastAPI entrypoint. Exposes:
  - `POST /orchestrator/answer` (set `stream=true` for SSE, default aggregated JSON)
  - `POST /feedback`
  - `GET /health`
- `app/orchestrator.py`  
  High-level pipeline orchestrator (`stream_answer_query`, `run_graph`).
- `app/intent_rewrite_router.py`  
  Single LLM call returning JSON: `rewritten_question`, `route` (`rag` | `direct_reply` | `clarify` | `reject`), `can_answer_directly`, `direct_answer`, `reason`. Server-side guard can force `rag` when `direct_reply` would touch sensitive/private topics.
- `app/agent_graph.py`  
  LangGraph with a single `retrieve` node (HTTP RAG once); formatted RAG payload is the response body (no `llm_call` / judge in the graph).
- `app/graph_judge.py` / `app/agent_answer_judge.py`  
  Unused by the current graph; retained for optional future quality loops.
- `app/agent_graph_state.py` / `app/graph_emit.py`  
  Shared graph state type and SSE `emit_state` helper.
- `app/rag_http_tool.py`  
  HTTP client for `POST {RAG_HTTP_BASE_URL}/v1/rag/query`.
- `app/agent_rewrite.py`  
  Third-person normalization (`rewrite_to_third_person`), history caps, and `history_snippet_for_answer` / `format_history_for_prompt` for the router and RAG configurable context.
- `app/logging_config.py` + `app/request_context.py`  
  Structured JSON logging with request/session context; shipped by external collectors (for example Alloy).

## Primary Flow: `/orchestrator/answer`

Clients may send user context in headers (`X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`); the orchestrator relays them on the outbound RAG `POST /v1/rag/query` (body fields `user_id`, `user_roles`, `user_groups`, `user_teams` are rejected).

1. Initialize request ids and emit SSE `{type:"request_id"}`.
2. **Intent / rewrite router** (one LLM): returns JSON with standalone `rewritten_question` and `route`.
3. Emit SSE `{type:"rewrite", "text": ...}` and `{type:"route", "route": ...}` (lowercase route values; breaking change from historical `"RAG"`).
4. Branch:
   - **`direct_reply`**: emit `answer` from `direct_answer` (common/greeting only; guard may have forced `rag`).
   - **`clarify`**: emit `answer` prompting the user (from `direct_answer` or a default).
   - **`reject`**: emit `answer` with refusal text.
   - **`rag`**: run LangGraph `retrieve` with `rewritten_question`; API `answer` is the RAG tool payload (formatted string from `rag_http_tool`).
5. Emit completion state or error event; successful streams end with `{type:"done"}`.

## LangGraph Design

### A) Deterministic HTTP RAG mode

Used when `RAG_HTTP_BASE_URL` is set and the router chose `route: "rag"`.

- Node `retrieve` calls HTTP RAG once and appends synthetic `AIMessage` + `ToolMessage` (evidence) for a stable message transcript.
- The orchestrator reads the last tool message body as the user-facing `answer` (no graph-level answer or judge LLM).

Why this exists:

- Avoids tool-calling protocol requirements on gateways that reject `tool_choice=auto/required` without parser flags.
- Router consolidates rewrite + routing into one gateway call before optional RAG.

## Data Contracts

### SSE events (`/orchestrator/answer` with `stream=true`)

Event types:

- `request_id`
- `state`
- `rewrite`
- `route`
- `answer`
- `error`
- `done` (success only; emitted after the final `request_complete` state)

After LangGraph returns on a `rag` path, `answer` (with optional `agent_graph_run_id`) is emitted immediately, then the orchestrator emits the `rag` phase `completed` state and remaining lifecycle events.

`state` events include `phase`, `status` (`running`, `completed`, `failed`, `skipped`), `ui_message`, optional timestamps, `latency_ms`, and `metadata`. High-level orchestrator phases include **`intent_router`** (single LLM rewrite+route), **`rag`**, and **`request_complete`**. During the LangGraph RAG phase, the only granular phase emitted is `rag_query` (HTTP RAG retrieve). Non-stream JSON includes one entry per `phase` with a **terminal** status (`completed`, `failed`, `skipped`). A prior `running` event for the same phase is **merged** into that entry (e.g. `started_at` from `running`, `ended_at` / `latency_ms` / `ui_message` from the terminal event, `metadata` shallow-merged). Pure `running` phases are omitted. Non-stream JSON includes a top-level `timings_ms` object with end-to-end `total`, phase timings (`intent_router`, `request_complete`), and nested `rag` timing where `rag.total` is the orchestrator wall timing for `rag_query` and `rag.service` is the RAG service breakdown from `rag_query.metadata.rag_latency_ms`.

### RAG HTTP request (`app/rag_http_tool.py`)

Payload:

- `question`
- `collection_base`
- `request_id`
- `session_id`
- `k`
- `k_max`
- `include_retrieval_hits`

### Feedback (`POST /feedback`)

Accepts user rating + optional type/comment and forwards to LangSmith when credentials exist.

## Observability

- Structured JSON logs with:
  - `request_id`, `session_id`, `method`, `path`, `status`, `phase` (pipeline step such as `intent_router`, `rag`, `rag_query`, `http`, or `-` when unset)
  - latency fields and error metadata when available
  - After each RAG HTTP call, INFO `rag_query_api_response` with `gateway_meta.rag_api_response` mirroring the RAG JSON (`answer`, `citations`, `follow_up_questions`, `latency_ms`; `retrieval_hits` omitted to limit log size) plus `http_status_code`
- Request context propagated via middleware/contextvars.
- Logs are written as JSON to stderr and can be collected/shipped by Alloy.
- LangSmith tags include model/project/request/session context.

## Configuration Strategy

- `LLM_GATEWAY_BASE_URL` is required for model calls.
- `RAG_HTTP_BASE_URL` is required and drives deterministic HTTP RAG graph execution.
- Timeouts:
  - `TOOLS_TIMEOUT_S` for RAG HTTP client timeout
  - `INVOKE_TIMEOUT_S` for graph invoke timeout

## Failure Handling

- Pipeline catches errors and emits SSE `{type:"error"}`.
- Exception groups are unwrapped to the first meaningful root cause.
- Logging includes structured error fields for triage.

## Trade-offs

- Deterministic HTTP RAG path favors compatibility and predictability over dynamic tool routing.
- Answers on the `rag` path are verbatim RAG-formatted tool text: tone and length follow the RAG service (`_format_rag_response` in `rag_http_tool`), not a dedicated answer model.
- One router LLM replaces separate intent + rewrite calls; router JSON parse failures conservatively fall back to `rag`.
