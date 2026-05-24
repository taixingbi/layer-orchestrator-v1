# System Design

This document explains the runtime design of `layer-orchestrator-v1`: components, request flows, reliability loops, and key trade-offs.

## Package layout

```
app/
  main.py, config.py, orchestrator.py   # entry + settings + compat re-exports
  api/          # FastAPI route handlers
  core/         # pipeline, router, rewrite, SSE, state
  clients/      # outbound HTTP (RAG, readiness)
  graph/        # legacy LangGraph (unused by default pipeline)
  observability/  # logging, context, metrics, usage, feedback
  intents/      # deterministic internal intents
  tools/        # user_profile, github_repo_search, web_search
  schemas/      # request/response/route models
  prompts/      # router prompts + small-talk seed
```

## Goals

- Provide a single API for question answering over Taixing-focused knowledge.
- Keep responses observable (SSE events + structured logs + Prometheus).
- Prefer grounded answers (RAG retrieval text returned as the user-visible answer when legacy `route` is `rag`; no separate answer synthesis LLM in the default pipeline).
- Keep integration simple with OpenAI-compatible inference gateways and optional MCP tool services.

## Runtime Components

- `app/main.py`  
  FastAPI entrypoint. Exposes:
  - `POST /orchestrator/answer` (set `stream=true` for SSE, default aggregated JSON)
  - `POST /orchestrator/eval/router`
  - `POST /feedback`
  - `GET /health` (liveness; config only)
  - `GET /ready` (readiness; probes LLM gateway and RAG HTTP)
  - `GET /metrics` (Prometheus)
- `app/api/routes.py`  
  HTTP handlers; validation, SSE vs JSON aggregation.
- `app/core/pipeline.py`  
  Primary orchestration (`stream_answer_query`): rewrite → route → internal intent | tool → answer.
- `app/core/router.py`  
  Router integration: `RouterDecision` → `route_detail`, deterministic intent pre-check.
- `app/core/intent_router.py`  
  Single LLM call returning JSON: `rewritten_question`, `route`, optional `route_detail`, `direct_answer`, `reason`. Pre-LLM: injection guard, small-talk seed. Post-LLM: KB-grounded overrides. See [intent-router.md](intent-router.md).
- `app/core/rewrite.py`  
  Third-person normalization, history caps, prompt formatting.
- `app/core/sse.py`  
  SSE wire format and non-stream JSON aggregation (`latency_ms`, `usage`).
- `app/core/state.py`  
  Shared `state` event shape for pipeline phases.
- `app/intents/`  
  Deterministic internal intents (`identity`, `greeting`, `help`, `capabilities`).
- `app/tools/`  
  `user_profile` (MCP `rag_query` or HTTP RAG), `github_repo_search` (MCP `ask_repo`), `web_search` (Tavily).
- `app/clients/rag_http.py`  
  HTTP client for `POST {RAG_HTTP_BASE_URL}/v1/rag/query`.
- `app/clients/ready.py`  
  Readiness probes for LLM gateway and RAG.
- `app/graph/`  
  Legacy LangGraph path (retained; **not used** by `app/core/pipeline.py`).
- `app/observability/`  
  Structured JSON logging, request context, Prometheus metrics, token usage, LangSmith feedback.

## Primary Flow: `/orchestrator/answer`

Field-by-field request and response schema: **[schema-request-response.md](schema-request-response.md)** (includes optional body **`conversation_id`**, effective id and **`is_new_conversation`** on responses and the first SSE event). Threading, logging, and downstream headers are summarized in **[conversation-id.md](conversation-id.md)**.

Clients may send user context in headers (`X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`); the orchestrator relays them on outbound RAG `POST /v1/rag/query`. Those fields and correlation ids (`session_id`, `request_id`, `trace_id`) are **rejected** if sent in the JSON body; **`conversation_id`** is the exception and may be sent in the body for threading.

1. Initialize request ids and emit SSE `{ "type":"request_id", "request_id", "session_id", "conversation_id", "is_new_conversation" }` (`conversation_id` is the effective id; server assigns `conv_<uuidhex>` when the body omits or blanks it).
2. **Intent / rewrite router** (one LLM when no server short-circuit): `resolve_route` may match deterministic internal intents first; otherwise `run_intent_rewrite_router` returns JSON with standalone `rewritten_question` and `route` / `route_detail`.
3. Emit SSE `{type:"rewrite", "text": ...}` and `{type:"route", "route": ..., "route_detail": ...}` (lowercase legacy route values).
4. Branch via **direct tool dispatch** in `app/core/pipeline.py`:
   - **`internal_intent`** (`identity`, `greeting`, `help`, `capabilities`): static answer from `app/intents/`.
   - **`direct_reply` / `clarify` / `reject`**: legacy routes mapped to internal intents; emit `answer` from `direct_answer`.
   - **`tool:user_profile`**: MCP `rag_query` or HTTP RAG; legacy flat `route` is `rag`.
   - **`tool:github_repo_search`**: MCP `ask_repo`; flat `route` is `tool`.
   - **`tool:web_search`**: Tavily search; flat `route` is `tool`.
5. Emit completion or error event; successful streams end with `{type:"done"}` (includes aggregated `latency_ms` and `usage`).

Detailed SSE sequence: **[architecture.md](architecture.md)**.

## HTTP RAG path (`tool:user_profile`)

When the router selects `user_profile`, the pipeline calls RAG directly:

- **Default:** `app/tools/user_profile.py` → MCP `rag_query` with `stream: true` when `MCP_RAG_BASE_URL` is set (`USE_MCP_RAG=true`, default).
- **HTTP fallback:** `USE_MCP_RAG=false` → `query_rag_http_with_meta` in `app/clients/rag_http.py` (single JSON response, no token streaming).

With MCP + `stream=true` on `/orchestrator/answer`, the orchestrator forwards **`answer_delta`** SSE events as tokens arrive, then a final **`answer`** with citations and usage.

The user-facing `answer` is the RAG service response text. No orchestrator answer LLM runs after retrieval.

## Data Contracts

### SSE events (`/orchestrator/answer` with `stream=true`)

**Wire events** (client-visible):

- `request_id`, `rewrite`, `route`, `answer_delta`, `answer`, `error`, `done`

**Internal `state` events** (logs, metrics, non-stream aggregation only — **not** sent on the SSE wire):

- Phases: `intent_router`, `rag`, `tool`, `request_complete`

Non-stream JSON (and stream `done.latency_ms`) include a nested `latency_ms` object: `total`, `intent_router.total`, and `rag` / `tool` objects with `orchestrator` plus RAG service breakdown keys.

### RAG HTTP request (`app/clients/rag_http.py`)

Payload: `question`, `collection_base`, `k`, `k_max`, `include_retrieval_hits`, optional `conversation_id`. Correlation and user fields travel on headers.

### Feedback (`POST /feedback`)

Accepts user rating + optional type/comment and forwards to LangSmith when credentials exist.

## Observability

- Structured JSON logs via `app/observability/logging.py` and `app/observability/context.py`
- Prometheus metrics at `/metrics`
- LangSmith tags when tracing is enabled

## Configuration Strategy

- `LLM_GATEWAY_BASE_URL` is required for router model calls.
- `RAG_HTTP_BASE_URL` is required for HTTP RAG (and as MCP RAG fallback base).
- Optional: `USE_MCP_TOOLS`, `MCP_GITHUB_BASE_URL`, `TAVILY_API_KEY`.

## Failure Handling

- Pipeline catches errors and emits SSE `{type:"error"}`.
- RAG HTTP retries transient failures with exponential backoff.

## Trade-offs

- Direct tool dispatch favors compatibility and lower latency over dynamic LangGraph tool routing.
- Answers on the `rag` path are verbatim RAG-formatted tool text.
- One router LLM replaces separate intent + rewrite calls; parse failures conservatively fall back to `rag`.
