# System Design

This document explains the runtime design of `layer-orchestrator-v1`: components, request flows, reliability loops, and key trade-offs.

## Goals

- Provide a single API for question answering over Taixing-focused knowledge.
- Keep responses observable (SSE events + structured logs).
- Prefer grounded answers (RAG evidence + answer judge loop).
- Keep integration simple with OpenAI-compatible inference gateways.

## Runtime Components

- `app/main.py`  
  FastAPI entrypoint. Exposes:
  - `POST /orchestrator/answer` (set `stream=true` for SSE, default aggregated JSON)
  - `POST /feedback`
  - `GET /health`
- `app/orchestrator.py`  
  High-level pipeline orchestrator (`stream_answer_query`, `run_graph`).
- `app/agent_graph.py`  
  LangGraph construction and reliability loop:
  - deterministic HTTP RAG mode (no model tool-calling)
  - judge + retry path
- `app/rag_http_tool.py`  
  HTTP client for `POST {RAG_HTTP_BASE_URL}/v1/rag/query`.
- `app/agent_rewrite.py`  
  Query rewrite (third-person normalization + LLM rewrite).
- `app/intent_gate.py`  
  Smalltalk gate (returns canned response for non-task chat).
- `app/agent_answer_judge.py`  
  Judge model for grounding/quality checks.
- `app/logging_config.py` + `app/request_context.py`  
  Structured JSON logging with request/session context; shipped by external collectors (for example Alloy).

## Primary Flow: `/orchestrator/answer`

1. Initialize request ids and emit SSE `{type:"request_id"}`.
2. Run intent gate:
   - If smalltalk: emit answer and finish.
3. Rewrite query:
   - deterministic second-person -> third-person conversion
   - LLM rewrite for retrieval clarity
4. Route to RAG (current behavior always routes to RAG when configured).
5. Execute LangGraph phase via `run_graph(...)`.
6. Emit final answer (plus `agent_graph_run_id` when available).
7. Emit completion state or error event.

## LangGraph Design

### A) Deterministic HTTP RAG mode

Used when `RAG_HTTP_BASE_URL` is set.

- Node `retrieve` calls HTTP RAG once.
- Graph creates synthetic tool/evidence messages so judge logic remains consistent.
- Node `llm_call` uses plain model invocation (no tool schema/tool_choice needed).
- Node `judge` validates answer; retries up to `MAX_RETRIES`.

Why this exists:
- Avoids tool-calling protocol requirements on gateways that reject `tool_choice=auto/required` without parser flags.

## Data Contracts

### SSE events (`/orchestrator/answer` with `stream=true`)

Event types:
- `request_id`
- `state`
- `rewrite`
- `route`
- `answer`
- `error`

`state` events include `phase`, `status` (`running`, `completed`, `failed`, `skipped`), `ui_message`, optional timestamps, `latency_ms`, and `metadata`. High-level phases from the orchestrator include `rewrite`, `route_decision`, `rag`, and `request_complete`. During the LangGraph RAG phase, granular phases are also emitted (in order): `rag_query` (HTTP RAG retrieve), `llm_call` / `llm_call_retry` (second attempt when the judge requests a rewrite), `judge` / `judge_retry`, and `judge_retry` with `skipped` when the judge short-circuits after max retries. Non-stream JSON includes one entry per `phase` with a **terminal** status (`completed`, `failed`, `skipped`). A prior `running` event for the same phase is **merged** into that entry (e.g. `started_at` from `running`, `ended_at` / `latency_ms` / `ui_message` from the terminal event, `metadata` shallow-merged). Pure `running` phases are omitted. Retry steps still use distinct phase names (`llm_call_retry`, `judge_retry`) where both attempts should appear. Non-stream JSON includes a top-level `timings_ms` object with end-to-end `total`, phase timings (`rewrite`, `route_decision`, `llm_call`, `judge`, `request_complete`), and nested `rag` timing where `rag.total` is the orchestrator wall timing for `rag_query` and `rag.service` is the RAG service breakdown from `rag_query.metadata.rag_latency_ms`.

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
  - `request_id`, `session_id`, `method`, `path`, `status`
  - latency fields and error metadata when available
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
- Judge fallback defaults to pass if judge output is unparsable (prevents hard dead-end on judge parse failures).
- Logging includes structured error fields for triage.

## Trade-offs

- Deterministic HTTP RAG path favors compatibility and predictability over dynamic tool routing.
- Single retry (`MAX_RETRIES = 1`) limits latency but may leave some borderline answers unimproved.
- Intent gate + rewrite improve retrieval quality but add extra LLM calls and latency.
