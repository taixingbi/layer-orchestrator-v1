# Request and response schema

HTTP request bodies, headers, and JSON/SSE response shapes for this service. Correlation ids (`session_id`, `request_id`, `trace_id`) and user relay fields **must** be sent on headers only; sending them in the JSON body returns **400**. Optional **`conversation_id`** (client thread id) may be sent in the JSON body for `/orchestrator/answer` and `/orchestrator/eval/router`. If omitted, null, or whitespace-only after trim, the server assigns `conv_<uuidhex>` and sets **`is_new_conversation`: true**; otherwise the client id is used and **`is_new_conversation`** is **false**. Responses include the effective **`conversation_id`** and **`is_new_conversation`**. For threading, logs, and outbound gateway/RAG behavior, see **[conversation-id.md](conversation-id.md)**.

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
  "history": [],
  "conversation_id": "string (optional)"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question` | string | — | Latest user message |
| `stream` | boolean | `false` | `true` → SSE (`text/event-stream`); `false` → single JSON object |
| `history` | array | `[]` | Prior turns; each item `{ "role": "user" \| "assistant", "content": "string" }` |
| `conversation_id` | string | `null` | Optional client-owned thread id (max 256 chars after trim). Blank → server assigns `conv_<uuidhex>`; see **`is_new_conversation`** on responses |

**Rejected in body (400):** `session_id`, `request_id`, `trace_id`, `user_id`, `user_roles`, `user_groups`, `user_teams`.

### Workflow safety limits

The orchestrator enforces configurable request safety limits:

- `MAX_REQUEST_BODY_MB` (default `1`)
- `MAX_HISTORY_MESSAGES` (default `50`)
- `MAX_QUESTION_CHARS` (default `8000`)
- `MAX_CONTEXT_CHARS` (default `120000`, computed as `len(question) + sum(len(history[i].content)) + len(conversation_id)` using the **effective** conversation id after optional server assignment)
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
  "conversation_id": "string",
  "is_new_conversation": false,
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
| `conversation_id` | Always — effective thread id (client or server `conv_<uuidhex>`) |
| `is_new_conversation` | Always — `true` if the server assigned a new id this request |
| `rewrite` | After router emits rewrite |
| `answer` | After an answer is produced |
| `citations` | Always — populated from RAG when `route` is `rag`; otherwise `[]` |
| `follow_up_questions` | Always — populated from RAG when `route` is `rag`; otherwise `[]` |

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
  "error": "request timeout exceeded",
  "request_id": "string | null",
  "session_id": "string | null",
  "trace_id": "string | null",
  "conversation_id": "string",
  "is_new_conversation": false
}
```

---

## `POST /orchestrator/answer` — stream (`stream: true`)

Response: **SSE**, each line `data: <json>\n\n`.

### Event types

| `type` | Description |
|--------|-------------|
| `request_id` | `{ "type": "request_id", "request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation" }` — early correlation (`conversation_id` is always the effective id; omitted keys besides these may be null) |
| `rewrite` | `{ "type": "rewrite", "text": "..." }` |
| `route` | `{ "type": "route", "route": "rag" \| ... }` |
| `answer` | `{ "type": "answer", "text": "...", "citations": [], "follow_up_questions": [] }` — RAG fills arrays when the service returns them |
| `done` | `{ "type": "done", "request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation", "timings_ms" }` — success end; **`timings_ms`** same shape as non-stream JSON |
| `error` | `{ "type": "error", "text": "...", "request_id", "session_id", "trace_id", "conversation_id", "is_new_conversation", "timings_ms"? }` — failure; **`timings_ms`** present when terminal phase states were recorded |

**Phase `state` events are not sent on the SSE wire** (they remain in structured logs and Prometheus). Use non-stream JSON (`stream: false`) for `timings_ms` built from internal phase state.

Typical successful stream sequence: `request_id` → `rewrite` → `route` → `answer` → `done` (with `timings_ms`).

Timeout examples in stream mode:

- `{"type":"error","text":"Error: TimeoutError: request timeout exceeded"}`
- `{"type":"error","text":"Error: TimeoutError: stream idle timeout exceeded"}`

---

## `POST /orchestrator/eval/router`

Router-only evaluation endpoint. Runs rewrite/route logic and deterministic checks only; it does **not** run RAG or graph execution.

### Headers (optional)

Same correlation headers as `/orchestrator/answer`:

- `X-Session-Id`
- `X-Request-Id`
- `X-Trace-Id`

### JSON body

```json
{
  "question": "string (required)",
  "expected_route": "rag | direct_reply | clarify | reject (optional)",
  "conversation_id": "string (optional)",
  "router_model": "string (optional; default: LLM_MODEL)",
  "router_temperature": 0,
  "router_prompt_version": "string (optional; versioned prompt file id)",
  "router_prompt_override": "string (optional; replaces file-based prompt for this request)",
  "history": []
}
```

`history` items use the same shape as `/orchestrator/answer`: `{ "role": "user" | "assistant", "content": "string" }`.

When `expected_route` is set, the response includes `evaluation.route_match` and `evaluation.checks.route_match` comparing it to `decision.route`. When omitted, `evaluation.expected_route` and `evaluation.route_match` are `null` (no expectation); `checks.route_match` is still `true` (vacuous pass).

**Prompt-injection guard (latest message, hard logic):** Before the router LLM and before small-talk, the server may match normalized patterns for known jailbreak / exfil attempts and return **`reject`**. Then `router.prompt_source` is **`injection_guard`**, `router.prompt_file` is **`null`**, and `router.smalltalk_intent` is **`null`**. This does not replace authorization on tools or data; see [intent-router.md](intent-router.md).

**Small-talk (empty history):** If the injection guard does not apply and `history` is empty or omitted, the server tries **two** layers before the router LLM (see [`app/intent_rewrite_router.py`](../app/intent_rewrite_router.py)):

1. **Exact seed** — Normalized exact equality to a `user_examples` string in `app/prompts/smalltalk_examples.json`. Then `router.prompt_source` is **`smalltalk_seed`**.
2. **Pattern layer** — Short utterances (length cap) that **fullmatch** a small set of regexes map to an **`intent`**; the **`answer`** is still read from the JSON row with that `intent`. Then `router.prompt_source` is **`smalltalk_pattern`**.

In both cases the response is **`direct_reply`** with that `answer` (no router LLM). `router.prompt_file` is **`null`**, and `router.smalltalk_intent` is the matched **`intent`**. Answers in JSON may contain `__CANDIDATE_NAME__`; it is replaced at match time like prompt files.

**Versioned router prompts** (when `router_prompt_override` is omitted): the system prompt is read from `app/prompts/{router_prompt_version}.txt` (plain text only; no separate loader module). If `router_prompt_version` is omitted, the file id defaults to `ROUTER_PROMPT_VERSION` (env) or `router-v1.00`. Version ids must match `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`. If the requested file is missing, the server falls back to `router-v1.00.txt` and reports that in `router.prompt_fallback_from`. Prompt files may contain the literal placeholder `__CANDIDATE_NAME__`; it is replaced at load time with the configured candidate name.

`router_prompt_override` and the **effective** **`conversation_id`** length count toward `MAX_CONTEXT_CHARS` together with the question and history message bodies.

### Response (`200`)

```json
{
  "request_id": "string | null",
  "session_id": "string | null",
  "trace_id": "string | null",
  "conversation_id": "string",
  "is_new_conversation": false,
  "router": {
    "model": "string",
    "temperature": 0,
    "prompt_version": "string | null",
    "prompt_source": "versioned_file | body_override | injection_guard | smalltalk_seed | smalltalk_pattern",
    "prompt_file": "router-v1.00 | null",
    "prompt_fallback_from": "string | null",
    "smalltalk_intent": "string | null",
    "prompt_override_used": false
  },
  "decision": {
    "rewritten_question": "string",
    "route": "rag | direct_reply | clarify | reject",
    "answer": "string | null",
    "reason": "string"
  },
  "evaluation": {
    "expected_route": "direct_reply | null",
    "actual_route": "direct_reply",
    "route_match": true,
    "all_checks_pass": true,
    "checks": {
      "has_rewrite": true,
      "route_valid": true,
      "route_match": true,
      "direct_reply_has_answer": true,
      "history_followup_rewritten": true
    },
    "notes": []
  },
  "status": "ok"
}
```

### Evaluation checks

- `has_rewrite`: rewritten question is non-empty.
- `route_valid`: route is one of `rag`, `direct_reply`, `clarify`, `reject`.
- `route_match` (top-level and in `checks`): when `expected_route` is provided, compares to `actual_route`; when omitted, top-level `route_match` is `null` and `checks.route_match` is `true`.
- `direct_reply_has_answer`: when route is `direct_reply`, `decision.answer` (router inline reply) is non-empty; for `rag` / `clarify` / `reject`, `answer` may be null or carry clarify/reject text from the router.
- `history_followup_rewritten`: if history is present, rewritten question differs from raw question.

`evaluation.all_checks_pass` is `true` only when every entry in `checks` is `true`.

Top-level **`conversation_id`** is always the effective thread id (client or server-assigned **`conv_<uuidhex>`**). **`is_new_conversation`** is **`true`** when the server generated a new id for this request.

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
