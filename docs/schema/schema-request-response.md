# Request and response schema

HTTP request bodies, headers, and JSON/SSE response shapes for this service. Correlation ids (`session_id`, `request_id`, `trace_id`) and user relay fields **must** be sent on headers only; sending them in the JSON body returns **400**. Optional **`conversation_id`** (client thread id) may be sent in the JSON body for `/v1/orchestrator/answer` and `/v1/orchestrator/eval/router`. If omitted, null, or whitespace-only after trim, the server assigns `conv_<uuidhex>` and sets **`is_new_conversation`: true**; otherwise the client id is used and **`is_new_conversation`** is **false**. Responses include the effective **`conversation_id`** and **`is_new_conversation`**. For threading, logs, and outbound gateway/RAG behavior, see **[conversation-id.md](conversation-id.md)**.

---

## `POST /v1/orchestrator/answer`

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
  "stream": true,
  "history": [],
  "conversation_id": "string (optional)"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `question` | string | — | Latest user message |
| `stream` | boolean | `true` | `true` → SSE (`text/event-stream`); `false` → single JSON object |
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

## Response envelope (`stream: false` and terminal SSE `done` / `error`)

Non-stream JSON and the **final** SSE `done` / `error` event use the **same** top-level shape (aligned with [tool upstream schema](schema-tool.md)). Intermediate stream events (`rewrite`, `route`, `answer_delta`) are optional; clients may use only `done` / `error`. Full skeleton and examples: [schema-response-pattern.md](schema-response-pattern.md).

### Top-level fields

| Field | Description |
|-------|-------------|
| `meta` | Correlation, `user`, routing (`route`; `tool` only when a tool ran), optional `rewrite` |
| `answer` | `{ "text", "citations" }` |
| `follow_up_questions` | string[] |
| `latency_ms` | `intent_router`, `tool_rag` / `tool_github_search` / `tool_tavily_search`, `total` |
| `usage` | `intent_router`, tool phase passthrough, rolled-up `total` |
| `status` | `{ "ok", "state": "completed" \| "failed", "code": "ok" \| "error" \| "tool_timeout" \| ... }` |
| `error` | Present when `status.ok` is false |

### `meta.route` / `meta.tool`

| Handler | `meta.route.type` | Route id field | `meta.tool` (if any) |
|---------|-------------------|----------------|----------------------|
| `rag_private_kb` | `tool` | `meta.route.tool` | `{ name, type, version, key }` |
| `github_search` | `tool` | `meta.route.tool` | same |
| `web_search` | `tool` | `meta.route.tool` | same |
| internal intents | `internal_intent` | `meta.route.intent` | **omitted** (no tool ran) |

| `meta.route.source` | When set |
|---------------------|----------|
| `deterministic_rule` | Pre-LLM match (`app/intents/`, `github_route`) |
| `llm_router` | Default router LLM (`router-v3.00.txt`) |
| `smalltalk_seed` / `smalltalk_pattern` | Empty-history small-talk |
| `injection_guard` | Prompt-injection block |
| `override_rule` | Post-LLM server override (GitHub keywords, KB-grounded, general immigration, empty direct_reply → clarify) |

Orchestrator handler ids in `meta.route.tool` / `meta.tool.name`. `meta.tool.key` matches `latency_ms` / `usage` phase keys (`tool_rag`, `tool_github_search`, `tool_tavily_search`).

### Tool timing / usage keys

| Handler | `latency_ms` / `usage` key |
|---------|----------------------------|
| `rag_private_kb` | `tool_rag` |
| `github_search` | `tool_github_search` |
| `web_search` | `tool_tavily_search` |

`latency_ms.tool_*` and `usage.tool_*` are **passthrough** of upstream MCP/HTTP payloads ([schema-tool.md](schema-tool.md)). `latency_ms.intent_router.total` is orchestrator router wall time. `usage.total` sums all phases.

### Canonical skeleton and examples

Placeholder JSON, stream vs non-stream notes, failure shape, and smoke-test examples: **[schema-response-pattern.md](schema-response-pattern.md#canonical-skeleton)**.

---

### Error (`500`)

Same envelope where possible, plus top-level `error`:

```json
{
  "meta": { "request_id": "...", "conversation_id": "...", "is_new_conversation": false },
  "answer": { "text": "", "citations": [] },
  "follow_up_questions": [],
  "latency_ms": {},
  "usage": {},
  "status": { "ok": false, "state": "failed" },
  "error": "Error: ValueError: ..."
}
```

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

## `POST /v1/orchestrator/answer` — stream (`stream: true`, default)

Response: **SSE**, each line `data: <json>\n\n`.

| `type` | Description |
|--------|-------------|
| `correlation` | First frame: `request_id`, `session_id`, `trace_id`, `conversation_id`, `is_new_conversation` (legacy alias: `type: "request_id"`) |
| `rewrite` | `{ "type": "rewrite", "text": "..." }` |
| `route` | `{ "type": "route", "route": "<legacy flat>", "route_detail": { ... }, "route_source": "...", "text": "<rewrite>" }` — see [schema-response-pattern.md](schema-response-pattern.md) |
| `answer_delta` | `{ "type": "answer_delta", "text": "..." }` only (text chunks; concatenated on the client or in terminal `done`) |
| `done` | **Full response envelope** (see above) plus `"type": "done"` |
| `error` | **Full envelope** with `status.ok: false`, plus `"type": "error"`, `"text"` |

The **`done`** object is the client envelope (`meta`, `answer`, `latency_ms`, `usage`, `status`).

---

## `POST /v1/orchestrator/eval/router`

Router-only evaluation endpoint. Runs rewrite/route logic and deterministic checks only; it does **not** run RAG or graph execution.

### Headers (optional)

Same correlation headers as `/v1/orchestrator/answer`:

- `X-Session-Id`
- `X-Request-Id`
- `X-Trace-Id`

### JSON body

```json
{
  "question": "string (required)",
  "expected_route": "rag | direct_reply | clarify | reject | tool (optional)",
  "conversation_id": "string (optional)",
  "router_model": "string (optional; default: ROUTER_MODEL env, then LLM_MODEL)",
  "router_temperature": 0,
  "router_prompt_version": "string (optional; versioned prompt file id)",
  "router_prompt_override": "string (optional; replaces file-based prompt for this request)",
  "history": []
}
```

`history` items use the same shape as `/v1/orchestrator/answer`: `{ "role": "user" | "assistant", "content": "string" }`.

When `expected_route` is set, the response includes `evaluation.route_match` and `evaluation.checks.route_match` comparing it to `decision.route`. When omitted, `evaluation.expected_route` and `evaluation.route_match` are `null` (no expectation); `checks.route_match` is still `true` (vacuous pass).

**Prompt-injection guard (latest message, hard logic):** Before the router LLM and before small-talk, the server may match normalized patterns for known jailbreak / exfil attempts and return **`reject`**. Then `router.prompt_source` is **`injection_guard`**, `router.prompt_file` is **`null`**, and `router.smalltalk_intent` is **`null`**. This does not replace authorization on tools or data; see [intent-router.md](intent-router.md).

**Small-talk (empty history):** If the injection guard does not apply and `history` is empty or omitted, the server tries **two** layers before the router LLM (see [`app/core/intent_router.py`](../app/core/intent_router.py)):

1. **Exact seed** — Normalized exact equality to a `user_examples` string in `app/prompts/seed_intents/*.json`. Then `router.prompt_source` is **`smalltalk_seed`**.
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
    "route": "rag | direct_reply | clarify | reject | tool",
    "route_detail": { "type": "tool", "name": "rag_private_kb" },
    "legacy_route": "rag",
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
- `route_valid`: route is one of `rag`, `direct_reply`, `clarify`, `reject`, `tool`.
- `route_match` (top-level and in `checks`): when `expected_route` is provided, compares to `actual_route`; when omitted, top-level `route_match` is `null` and `checks.route_match` is `true`.
- `direct_reply_has_answer`: when route is `direct_reply`, `decision.answer` (router inline reply) is non-empty; for `rag` / `clarify` / `reject`, `answer` may be null or carry clarify/reject text from the router.
- `history_followup_rewritten`: if history is present, rewritten question differs from raw question.

`evaluation.all_checks_pass` is `true` only when every entry in `checks` is `true`.

Top-level **`conversation_id`** is always the effective thread id (client or server-assigned **`conv_<uuidhex>`**). **`is_new_conversation`** is **`true`** when the server generated a new id for this request.

---

## `POST /v1/feedback`

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

### Response (SSE)

Always `text/event-stream`, single event per request:

- Success: `data: {"type":"done","status":"ok","message":"Feedback received",...}\n\n`
- Invalid `feedback_type`: `data: {"type":"error","status":"error","message":"...","text":"..."}\n\n`

Optional correlation fields on the event: `request_id`, `session_id`, `trace_id` (from headers when present).

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

## `GET /version`

### Response (`200`)

Returns the deployment version id (same value as `app_version` on `/health` — from `APP_VERSION` env or package metadata).

```json
{
  "version_id": "string"
}
```

---

## `GET /ready`

Readiness probe: calls the **LLM gateway** (`POST …/v1/chat/completions` with `max_tokens: 1`) and the **RAG service** (`POST …/v1/rag/query` with probe question from `READINESS_RAG_QUESTION`, default `"."`). Uses `READINESS_TIMEOUT_S` (default `5`) per request.

RAG may return **HTTP 400** with `No chunks retrieved for this query` when the probe has no hits; that still counts as **healthy** (service reachable). Other **4xx/5xx** responses or transport errors mark RAG as failed.

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
- `orchestrator_rag_duration_seconds` (histogram; from completed `rag` phase)
- `orchestrator_pipeline_errors_total`
- `orchestrator_timeouts_total` (labels include timeout kind)

---

## Upstream tool payloads

MCP services return the shape in [schema-tool.md](schema-tool.md). The orchestrator maps `answer.text` → client `answer.text`, tool `latency_ms` → `latency_ms.tool_rag` (etc.), tool `usage` → `usage.tool_rag` (etc.).

---