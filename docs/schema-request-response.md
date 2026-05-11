# Request and response schema

HTTP request bodies, headers, and JSON/SSE response shapes for this service. Correlation ids (`session_id`, `request_id`, `trace_id`) and user relay fields **must** be sent on headers only; sending them in the JSON body returns **400**.

---

## `POST /orchestrator/answer`

### Headers (optional unless noted)

| Header | Purpose |
|--------|---------|
| `Content-Type` | `application/json` |
| `X-Session-Id` | Session scope for logs and downstream RAG |
| `X-Request-Id` | Request id; generated if omitted |
| `X-Trace-Id` | Trace id; defaults to `X-Request-Id` if omitted |
| `X-User-Id` | Forwarded to RAG HTTP as `user_id` |
| `X-User-Roles` | RAG: `user_roles` |
| `X-User-Groups` | RAG: `user_groups` |
| `X-User-Teams` | RAG: `user_teams` |

Response includes `X-Request-Id` (middleware).

### JSON body

```json
{
  "question": "string (required)",
  "stream": false,
  "history": []
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question` | string | — | Latest user message |
| `stream` | boolean | `false` | `true` → SSE (`text/event-stream`); `false` → single JSON object |
| `history` | array | `[]` | Prior turns; each item `{ "role": "user" \| "assistant", "content": "string" }` |

**Rejected in body (400):** `session_id`, `request_id`, `trace_id`, `user_id`, `user_roles`, `user_groups`, `user_teams`.

### Workflow safety limits

The orchestrator enforces configurable request safety limits:

- `MAX_REQUEST_BODY_MB` (default `1`)
- `MAX_HISTORY_MESSAGES` (default `50`)
- `MAX_QUESTION_CHARS` (default `8000`)
- `MAX_CONTEXT_CHARS` (default `120000`, computed as `len(question) + sum(len(history[i].content))`)
- `REQUEST_TIMEOUT_MS` (default `30000`)
- `STREAM_IDLE_TIMEOUT_MS` (default `30000`, stream mode only)

Violations and timeout behavior:

- `413` when request body is too large.
- `400` when question/history/context validation fails.
- `504` for non-stream request timeout (`REQUEST_TIMEOUT_MS` exceeded).
- Stream mode emits an SSE `error` event and closes when request timeout or stream idle timeout is exceeded.

---

## `POST /orchestrator/answer` — non-stream (`stream: false`)

### Success (`200`)

```json
{
  "request_id": "string",
  "session_id": "string | null",
  "trace_id": "string",
  "route": "rag" | "direct_reply" | "clarify" | "reject",
  "rewrite": "string | null",
  "answer": "string | null",
  "citations": [],
  "follow_up_questions": [],
  "timings_ms": {},
  "status": "ok"
}
```

| Field | When present |
|-------|----------------|
| `rewrite` | After router emits rewrite |
| `answer` | After an answer is produced |
| `citations` | RAG path only, when the RAG service returned `citations` |
| `follow_up_questions` | RAG path only, when the RAG service returned `follow_up_questions` |

**`route`** is lowercase (intent/rewrite router output).

### `timings_ms` (non-stream aggregation)

Built from terminal `state` phases only (`completed`, `failed`, or `skipped`). Typical keys:

| Key | Meaning |
|-----|---------|
| `total` | Wall time across those phases (from earliest `started_at` to latest `ended_at`), milliseconds |
| `intent_router` | Router LLM phase latency |
| `rag` | Object; see below |
| `request_complete` | Marker phase; event often uses `latency_ms: 0` — use `total` for end-to-end |

**`rag`** (when RAG ran):

```json
{
  "total": 0,
  "service": {}
}
```

- `rag.total` — orchestrator-side timing for the LangGraph `rag_query` phase.
- `rag.service` — RAG HTTP JSON `latency_ms` breakdown when available (e.g. `embed`, `retrieve`, `chat`, `total`, …).

There is **no** top-level `latency_ms`; use **`timings_ms.total`**.

### Error (`500`)

Same fields as far as they were accumulated, plus:

```json
{
  "status": "error",
  "error": "string"
}
```

`timings_ms` may still be present if terminal state events were recorded.

### Validation / timeout errors

- `400` validation error:

```json
{
  "detail": "question too long: ... (MAX_QUESTION_CHARS)"
}
```

- `413` payload too large:

```json
{
  "status": "error",
  "error": "request body too large: ... (MAX_REQUEST_BODY_MB=...)"
}
```

- `504` request timeout:

```json
{
  "status": "error",
  "error": "request timeout exceeded"
}
```

---

## `POST /orchestrator/answer` — stream (`stream: true`)

Response: **SSE**, each line `data: <json>\n\n`.

### Event types

| `type` | Description |
|--------|-------------|
| `request_id` | `{ "type": "request_id", "request_id", "session_id" }` — early correlation |
| `rewrite` | `{ "type": "rewrite", "text": "..." }` |
| `route` | `{ "type": "route", "route": "rag" \| ... }` |
| `state` | Phase progress; see **State object** below |
| `answer` | `{ "type": "answer", "text": "..." }`; on RAG path may include `citations`, `follow_up_questions` when returned by RAG |
| `done` | `{ "type": "done" }` — success end |
| `error` | `{ "type": "error", "text": "..." }` — failure |

### State object (`type: "state"`)

```json
{
  "type": "state",
  "phase": "intent_router | rag | rag_query | request_complete | ...",
  "status": "running | completed | failed | skipped",
  "ui_message": "string",
  "message": "string (same as ui_message)",
  "started_at": "ISO8601 optional",
  "ended_at": "ISO8601 optional",
  "latency_ms": 0,
  "metadata": {}
}
```

Phases are emitted by the orchestrator and, during the graph, by the retrieve node (`rag_query`). Successful completion ends with `request_complete` + `done`.

Timeout examples in stream mode:

- `{"type":"error","text":"Error: TimeoutError: request timeout exceeded"}`
- `{"type":"error","text":"Error: TimeoutError: stream idle timeout exceeded"}`

---

## `POST /feedback`

### JSON body

```json
{
  "rating": "thumbs_up | thumbs_down",
  "agent_graph_run_id": null,
  "trace_id": null,
  "request_id": null,
  "question": null,
  "answer_snippet": null,
  "feedback_type": null,
  "comment": null
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `rating` | **yes** | `thumbs_up` or `thumbs_down` |
| `agent_graph_run_id` | no | LangSmith root run UUID if known |
| `trace_id` | no | Same as `X-Trace-Id` / answer JSON `trace_id` |
| `request_id` | no | Request correlation |
| `feedback_type` | no | One of: `not_relevant`, `biased`, `not_factual`, `incomplete_instructions`, `unsafe`, `style_tone`, `other` |
| `comment` | no | Free text |

LangSmith `create_feedback` is called only when credentials are configured. The run id passed to LangSmith is resolved in order: **`agent_graph_run_id` → `trace_id` → `request_id`**. LangSmith expects a valid traced run UUID unless your deployment maps ids differently.

### Responses

- Success: `{ "status": "ok", "message": "Feedback received" }`
- Invalid `feedback_type`: `{ "status": "error", "message": "..." }`

---

## `GET /health`

### Response (`200`)

```json
{
  "status": "ok",
  "app_version": "string",
  "app_name": "string",
  "langchain_project": "string | null",
  "langsmith_tracing": false,
  "langchain_endpoint": "string | null"
}
```

---

## `GET /ready`

Readiness probe: calls the **LLM gateway** (`POST …/v1/chat/completions` with `max_tokens: 1`) and the **RAG service** (`POST …/v1/rag/query` with a minimal body). Uses `READINESS_TIMEOUT_S` (default `5`) per request.

### Response (`200` when both dependencies are healthy)

```json
{
  "status": "ok",
  "dependencies": {
    "llm": {
      "ok": true,
      "status": "ok",
      "latency_ms": 120.5
    },
    "rag": {
      "ok": true,
      "status": "ok",
      "latency_ms": 45.2
    }
  }
}
```

### Response (`503` when any required dependency fails)

Same JSON shape with `status: "degraded"` and one or both of `dependencies.llm` / `dependencies.rag` having `"ok": false`. Failure objects may include `status` (`not_configured`, `timeout`, `error`), `error`, optional `detail`, and `latency_ms` (or `null` when not configured).

---

## `GET /metrics`

Prometheus text endpoint for HTTP and pipeline metrics.

### Response (`200`)

`Content-Type`: Prometheus/OpenMetrics text format (`text/plain; version=0.0.4; charset=utf-8`)

Example metric families exposed:

- `orchestrator_http_requests_total` (labels: `method`, `path`, `status`)
- `orchestrator_http_request_duration_seconds` (histogram)
- `orchestrator_route_decisions_total` (labels: `route`)
- `orchestrator_router_duration_seconds` (histogram)
- `orchestrator_rag_duration_seconds` (histogram; from `rag_query` phase)
- `orchestrator_pipeline_errors_total`
- `orchestrator_timeouts_total` (labels include timeout kind)

---

## RAG alignment ( `route: "rag"` )

When the upstream RAG HTTP service returns JSON with `answer`, `citations`, and `follow_up_questions`, the orchestrator mirrors **`answer`** (verbatim string), **`citations`**, and **`follow_up_questions`** on the non-stream JSON response and on the streaming **`answer`** event when those fields exist. Downstream RAG latency detail appears under **`timings_ms.rag.service`** when present.
