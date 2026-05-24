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

## Response envelope (`stream: false` and terminal SSE `done` / `error`)

Non-stream JSON and the **final** SSE event use the **same** top-level shape (aligned with [tool upstream schema](schema-tool.md)). Intermediate stream events (`rewrite`, `route`, `answer_delta`, partial `answer`) are optional; clients may use only `done` / `error`.

### Top-level fields

| Field | Description |
|-------|-------------|
| `meta` | Correlation, `user`, routing (`route`, `tool`), optional `rewrite` |
| `answer` | `{ "text", "citations" }` |
| `follow_up_questions` | string[] |
| `latency_ms` | `intent_router`, `tool_rag` / `tool_github_search` / `tool_tavily_search`, `total` |
| `usage` | `intent_router`, tool phase passthrough, rolled-up `total` |
| `status` | `{ "ok": boolean, "state": "completed" \| "failed" }` |
| `error` | Present when `status.ok` is false |

### `meta.route` / `meta.tool`

| Orchestrator handler | `meta.route.type` | `meta.route.tool` | `meta.tool.name` | `meta.tool.type` |
|----------------------|-------------------|-------------------|------------------|------------------|
| `user_profile` | `tool` | `rag_query` | `rag_query` | `rag` |
| `github_repo_search` | `tool` | `ask_repo` | `ask_repo` | `github` |
| `web_search` | `tool` | `web_search` | `web_search` | `web` |
| internal intents | `internal_intent` | intent name | intent name | `internal_intent` |

### Tool timing / usage keys

| Handler | `latency_ms` / `usage` key |
|---------|----------------------------|
| `user_profile` | `tool_rag` |
| `github_repo_search` | `tool_github_search` |
| `web_search` | `tool_tavily_search` |

`latency_ms.tool_*` and `usage.tool_*` are **passthrough** of upstream MCP/HTTP payloads ([schema-tool.md](schema-tool.md)). `latency_ms.intent_router.total` is orchestrator router wall time. `usage.total` sums all phases.

### Canonical skeleton

Placeholders show all possible keys; a given response only includes the tool phase that ran (`tool_rag` **or** `tool_github_search` **or** `tool_tavily_search`). Optional `meta.rag` / `meta.github` / `meta.web` appear on [upstream MCP payloads](schema-tool.md) only — the orchestrator does not copy them into client `meta` today.

**Non-stream** (`stream: false`): body matches the JSON below (no `type` field).

**Stream** (`stream: true`): final SSE `done` / `error` is the same object plus `"type": "done"` or `"type": "error"` (and `"text"` on errors).

```json
{
  "meta": {
    "request_id": "string",
    "session_id": "string | null",
    "trace_id": "string",
    "conversation_id": "string",
    "is_new_conversation": false,
    "user": {
      "id": "string",
      "roles": "string",
      "groups": "string",
      "teams": "string"
    },
    "route": {
      "type": "tool | internal_intent",
      "tool": "rag_query | ask_repo | web_search | <intent_name>",
      "confidence": 0.99,
      "reason": "optional string"
    },
    "tool": {
      "name": "rag_query | ask_repo | web_search",
      "type": "rag | github | web | internal_intent",
      "version": "v1"
    },
    "rewrite": "optional rewritten question"
  },
  "answer": {
    "text": "string",
    "citations": [
      {
        "cite_id": 1,
        "source": "string",
        "text": "string",
        "chunk_id": "optional",
        "repo": "optional",
        "url": "optional"
      }
    ]
  },
  "follow_up_questions": ["string"],
  "latency_ms": {
    "total": 0,
    "intent_router": { "total": 0 },
    "tool_rag": {
      "embed": 0,
      "retrieve_rerank": 0,
      "chat": 0,
      "follow_up_chat": 0,
      "total": 0
    },
    "tool_github_search": {
      "retrieve_rerank": 0,
      "chat": 0,
      "follow_up_chat": 0,
      "total": 0
    },
    "tool_tavily_search": {
      "search": 0,
      "chat": 0,
      "total": 0
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    },
    "intent_router": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    },
    "tool_rag": {
      "chat": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
      "follow_up_chat": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
      "total": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
    },
    "tool_github_search": {
      "chat": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
      "follow_up_chat": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
      "total": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
    },
    "tool_tavily_search": {
      "search": { "requests": 0 },
      "chat": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
      "total": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 }
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

On failure, add top-level `"error": "string"` and set `status.ok` to `false`, `status.state` to `"failed"`.

---

### Example: GitHub (`ask_repo`)

Question: *"in app of huntai, what is orchestrator design?"* — smoke-test style response (`stream: false` or SSE `done` with `"type": "done"` appended).

```json
{
  "meta": {
    "request_id": "req-123",
    "session_id": "ses-123",
    "trace_id": "req-123",
    "conversation_id": "conv-smoke-1",
    "is_new_conversation": false,
    "user": {
      "id": "taixing",
      "roles": "hr",
      "groups": "engineering",
      "teams": "rag-platform"
    },
    "route": {
      "type": "tool",
      "tool": "ask_repo",
      "confidence": 0.99,
      "reason": "Deterministic: HuntAI/layer repo or gateway architecture question"
    },
    "tool": {
      "name": "ask_repo",
      "type": "github",
      "version": "v1"
    },
    "rewrite": "in app of huntai, what is orchestrator design?"
  },
  "answer": {
    "text": "- The orchestrator design is described in the layer-orchestrator-v1 repository.\n- FastAPI service for chat completions, RAG, and unified responses.\n- Supports streaming via SSE.",
    "citations": [
      {
        "cite_id": 1,
        "source": "layer-mcp-github-v1 README",
        "text": "MCP server that answers natural-language questions about fixed GitHub repos."
      },
      {
        "cite_id": 4,
        "source": "layer-orchestrator-v1 README",
        "text": "FastAPI orchestrator for chat completions, RAG, and unified SSE responses."
      }
    ]
  },
  "follow_up_questions": [
    "What specific components are included in the main.py file of the orchestrator design?",
    "Can you explain how the orchestrator handles RAG?",
    "Which headers are used for tracing requests in the orchestrator?"
  ],
  "latency_ms": {
    "total": 7872.87,
    "intent_router": { "total": 1.36 },
    "tool_github_search": {
      "retrieve_rerank": 3934,
      "chat": 2546,
      "follow_up_chat": 1346,
      "total": 7854
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 318,
      "completion_tokens": 65,
      "total_tokens": 383
    },
    "tool_github_search": {
      "chat": {},
      "follow_up_chat": {
        "prompt_tokens": 318,
        "completion_tokens": 65,
        "total_tokens": 383
      },
      "total": {
        "prompt_tokens": 318,
        "completion_tokens": 65,
        "total_tokens": 383
      }
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

`usage.tool_github_search` is upstream passthrough (empty `chat` object allowed). `intent_router` usage is omitted when the router LLM did not run.

---

### Example: RAG (`rag_query` / `user_profile`)

Question: *"taixing visa status in us"*

```json
{
  "meta": {
    "request_id": "req-123",
    "session_id": "ses-123",
    "trace_id": "req-123",
    "conversation_id": "conv-smoke-1",
    "is_new_conversation": false,
    "user": {
      "id": "taixing",
      "roles": "hr",
      "groups": "engineering",
      "teams": "rag-platform"
    },
    "route": {
      "type": "tool",
      "tool": "rag_query",
      "confidence": 1.0
    },
    "tool": {
      "name": "rag_query",
      "type": "rag",
      "version": "v1"
    },
    "rewrite": "taixing visa status in us"
  },
  "answer": {
    "text": "Taixing Bi's visa status in the US is H4 EAD, and there is no need for visa sponsorship [1].",
    "citations": [
      {
        "cite_id": 1,
        "chunk_id": "1607b45e-1c07-5c29-975d-bbf47ef3129c",
        "source": "personal_profile",
        "text": "Q: What is Taixing Bi's visa status / work authorization?\nA: H4 EAD. No visa sponsorship required."
      }
    ]
  },
  "follow_up_questions": [
    "What does H4 EAD allow Taixing Bi to do in the US?",
    "Is Taixing Bi's H4 EAD permanent or temporary?",
    "Can Taixing Bi switch to another visa type if needed?"
  ],
  "latency_ms": {
    "total": 4826.92,
    "intent_router": { "total": 1997.75 },
    "tool_rag": {
      "embed": 138,
      "retrieve_rerank": 155,
      "chat": 678,
      "follow_up_chat": 1819,
      "total": 2799
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 1258,
      "completion_tokens": 166,
      "total_tokens": 1424
    },
    "intent_router": {
      "prompt_tokens": 516,
      "completion_tokens": 54,
      "total_tokens": 570
    },
    "tool_rag": {
      "chat": {
        "prompt_tokens": 319,
        "completion_tokens": 28,
        "total_tokens": 347
      },
      "follow_up_chat": {
        "prompt_tokens": 423,
        "completion_tokens": 84,
        "total_tokens": 507
      },
      "total": {
        "prompt_tokens": 742,
        "completion_tokens": 112,
        "total_tokens": 854
      }
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

Extra keys inside `usage.tool_rag` (e.g. `"type": "usage"`) are preserved when upstream sends them.

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

## `POST /orchestrator/answer` — stream (`stream: true`)

Response: **SSE**, each line `data: <json>\n\n`.

| `type` | Description |
|--------|-------------|
| `request_id` | Early correlation ids |
| `rewrite` | `{ "type": "rewrite", "text": "..." }` |
| `route` | `{ "type": "route", "route_detail": { ... } }` (internal; folded into final `meta`) |
| `answer_delta` | `{ "type": "answer_delta", "text": "..." }` |
| `answer` | `{ "type": "answer", "answer": { "text", "citations" }, "follow_up_questions": [] }` |
| `done` | **Full response envelope** (see above) plus `"type": "done"` |
| `error` | **Full envelope** with `status.ok: false`, plus `"type": "error"`, `"text"` |

The **`done`** object matches non-stream JSON (`meta`, `answer`, `latency_ms`, `usage`, `status`).

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
  "expected_route": "rag | direct_reply | clarify | reject | tool (optional)",
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

**Small-talk (empty history):** If the injection guard does not apply and `history` is empty or omitted, the server tries **two** layers before the router LLM (see [`app/core/intent_router.py`](../app/core/intent_router.py)):

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
    "route": "rag | direct_reply | clarify | reject | tool",
    "route_detail": { "type": "tool", "name": "user_profile" },
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
- `orchestrator_rag_duration_seconds` (histogram; from completed `rag` phase)
- `orchestrator_pipeline_errors_total`
- `orchestrator_timeouts_total` (labels include timeout kind)

---

## Upstream tool payloads

MCP services return the shape in [schema-tool.md](schema-tool.md). The orchestrator maps `answer.text` → client `answer.text`, tool `latency_ms` → `latency_ms.tool_rag` (etc.), tool `usage` → `usage.tool_rag` (etc.).

---