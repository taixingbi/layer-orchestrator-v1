# Response examples (`/v1/orchestrator/answer`)

Full JSON envelopes for common routes. **Terminal** SSE `done` / `error` carries the client envelope (plus `"type": "done"` or `"type": "error"`).

Request/headers/limits: [schema-request-response.md](schema-request-response.md). Upstream MCP payloads: [schema-tool.md](schema-tool.md). This doc holds the **canonical response skeleton** and route examples.

### Tool name ↔ timing / usage keys

| Orchestrator `meta.route.tool` / `meta.tool.name` | `meta.tool.type` | `meta.tool.key` (= `latency_ms` / `usage`) |
|---------------------------------------------------|------------------|---------------------------------------------|
| `user_profile` | `rag` | `tool_rag` |
| `github_search` | `github` | `tool_github_search` |
| `web_search` | `web` | `tool_tavily_search` |

### Stream vs `done`

During streaming, the server emits: `request_id` → `rewrite` → **`route`** → **`answer_delta`** (`text` only) → **`done`** (full envelope with citations / usage).

The **`route`** event always uses this shape (legacy flat `route` + nested `route_detail`):

```json
{
  "type": "route",
  "route": "tool | direct_reply | clarify | reject",
  "route_detail": {
    "type": "tool | internal_intent",
    "name": "user_profile | github_search | web_search | help | …",
    "confidence": 0.99,
    "reason": "optional string"
  },
  "route_source": "deterministic_rule | llm_router | smalltalk_seed | smalltalk_pattern | injection_guard | override_rule",
  "text": "<rewritten question>"
}
```

The **`done`** event uses the client envelope: `meta.route` is normalized (`tool` or `intent`, plus `source`); `meta.tool` is present **only** when a tool ran.

Examples below group stream events and the terminal **`done`** in one JSON object for readability (keys `request`, `rewrite`, `route`, … are **not** merged in a single live SSE line).

---

## Canonical skeleton

Placeholders show all possible keys; a given response only includes the tool phase that ran (`tool_rag` **or** `tool_github_search` **or** `tool_tavily_search`). Optional `meta.rag` / `meta.github` / `meta.web` appear on [upstream MCP payloads](schema-tool.md) only — the orchestrator does not copy them into client `meta` today.

**Answer** (always SSE): final `done` / `error` matches the JSON below plus `"type": "done"` or `"type": "error"` (and `"text"` on errors). Wire events use **`answer_delta`** only (no separate `answer` event type).

**Feedback** (`POST /v1/feedback`): always SSE; single `done` or `error` event with `status` and `message`.

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
      "tool": "user_profile | github_search | web_search (type tool only)",
      "intent": "help | clarify | reject | identity | greeting | capabilities (type internal_intent only)",
      "confidence": 0.99,
      "source": "deterministic_rule | llm_router | smalltalk_seed | smalltalk_pattern | injection_guard | override_rule",
      "reason": "optional string"
    },
    "tool": {
      "name": "user_profile | github_search | web_search",
      "type": "rag | github | web",
      "version": "v1",
      "key": "tool_rag | tool_github_search | tool_tavily_search"
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
    "state": "completed",
    "code": "ok"
  }
}
```

On failure, add top-level `"error": "string"` and set `status.ok` to `false`, `status.state` to `"failed"`, `status.code` to e.g. `"error"` or `"tool_timeout"`.

### Full examples (smoke-test)

| Route | Section |
|-------|---------|
| GitHub `github_search` | [GitHub (`github_search`)](#github-github_search) |
| RAG `user_profile` | [RAG (`user_profile`)](#rag-user_profile) |

---

## GitHub (`github_search`)

**Question:** *"in app of huntai, what is orchestrator design?"*

```bash
curl -N -sS -X POST http://192.168.86.179:30184/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "in app of huntai, what is orchestrator design?",
    "stream": true,
    "conversation_id": "conv-smoke-1"
  }'
```

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
      "tool": "github_search",
      "confidence": 0.99,
      "reason": "Deterministic: HuntAI/layer repo or gateway architecture question",
      "source": "deterministic_rule"
    },
    "tool": {
      "name": "github_search",
      "type": "github",
      "version": "v1",
      "key": "tool_github_search"
    },
    "rewrite": "in app of huntai, what is orchestrator design?"
  },
  "stream": [
    {
      "type": "request_id",
      "session_id": "ses-123",
      "request_id": "req-123",
      "trace_id": "req-123",
      "conversation_id": "conv-smoke-1",
      "is_new_conversation": false
    },
    {
      "type": "rewrite",
      "text": "in app of huntai, what is orchestrator design?"
    },
    {
      "type": "route",
      "route": "tool",
      "route_detail": {
        "type": "tool",
        "name": "github_search",
        "confidence": 0.99,
        "reason": "Deterministic: HuntAI/layer repo or gateway architecture question"
      },
      "route_source": "deterministic_rule",
      "text": "in app of huntai, what is orchestrator design?"
    }
  ],
  "answer": {
    "text": "- The orchestrator design is described in the README of [4] layer-orchestrator-v1.\n- It acts as an HTTP chat completions service via `POST /v1/chat/completions`.\n- Supports HTTP RAG (Retrieval-Augmented Generation).\n- Provides a unified `/v1/orchestrator/answer` endpoint with optional SSE support.\n- Handles correlation IDs in headers like `X-Request-Id`, `X-Session-Id`, and `X-Trace-Id`.",
    "citations": [
      {
        "cite_id": 1,
        "source": "layer-mcp-github-v1 README"
      },
      {
        "cite_id": 2,
        "source": "layer-web-v1 README"
      },
      {
        "cite_id": 3,
        "source": "layer-gateway-api-v1 README"
      },
      {
        "cite_id": 4,
        "source": "layer-orchestrator-v1 README"
      },
      {
        "cite_id": 5,
        "source": "layer-rag-query-v1 README"
      },
      {
        "cite_id": 6,
        "source": "layer-gateway-inference-v1 README"
      },
      {
        "cite_id": 7,
        "source": "layer-gateway-embed-v1 README"
      },
      {
        "cite_id": 8,
        "source": "layer-gateway-reranker-v1 README"
      },
      {
        "cite_id": 9,
        "source": "layer-rag-ingest-v1 README"
      },
      {
        "cite_id": 10,
        "source": "k3s README"
      },
      {
        "cite_id": 11,
        "source": "layer-grafana-loki-central-logger README"
      }
    ]
  },
  "follow_up_questions": [
    "What are the main components of the orchestrator design?",
    "Can you explain how the orchestrator handles HTTP requests?",
    "Is there any specific configuration needed for SSE support?"
  ],
  "latency_ms": {
    "total": 7621.55,
    "intent_router": {
      "total": 1.48
    },
    "tool_github_search": {
      "retrieve_rerank": 3770,
      "chat": 2917,
      "follow_up_chat": 887,
      "total": 7586
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 307,
      "completion_tokens": 42,
      "total_tokens": 349
    },
    "tool_github_search": {
      "total": {
        "prompt_tokens": 307,
        "completion_tokens": 42,
        "total_tokens": 349
      }
    }
  },
  "status": {
    "ok": true,
    "state": "completed",
    "code": "ok"
  },
  "type": "done"
}
```

**Notes**

- **`route.route_source`** is `deterministic_rule` when `resolve_route` / `github_route` short-circuits before the router LLM.
- **`usage.intent_router`** is omitted when the router LLM did not run.
- MCP upstream may send only `usage.total`; orchestrator passthroughs it under `usage.tool_github_search`.

---

## RAG (`user_profile`)

**Question:** *"taixing visa status in us"*

```bash
curl -N -sS -X POST http://192.168.86.179:30184/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "what is taixing visa status in us?",
    "conversation_id": "conv-smoke-1"
  }'
```

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
      "tool": "user_profile",
      "confidence": 1.0,
      "reason": "Needs Taixing Bi-specific facts",
      "source": "llm_router"
    },
    "tool": {
      "name": "user_profile",
      "type": "rag",
      "version": "v1",
      "key": "tool_rag"
    },
    "rewrite": "taixing visa status in us"
  },
  "stream": [
    {
      "type": "request_id",
      "session_id": "ses-123",
      "request_id": "req-123",
      "trace_id": "req-123",
      "conversation_id": "conv-smoke-1",
      "is_new_conversation": false
    },
    {
      "type": "rewrite",
      "text": "taixing visa status in us"
    },
    {
      "type": "route",
      "route": "tool",
      "route_detail": {
        "type": "tool",
        "name": "user_profile",
        "confidence": 1.0,
        "reason": "Needs Taixing Bi-specific facts"
      },
      "route_source": "llm_router",
      "text": "taixing visa status in us"
    }
  ],
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
    "Can Taixing Bi switch to a different visa type in the future?",
    "Does Taixing Bi need to renew the H4 EAD periodically?",
    "What are the requirements for maintaining H4 EAD status?"
  ],
  "latency_ms": {
    "total": 5078.02,
    "intent_router": {
      "total": 2276.61
    },
    "tool_rag": {
      "embed": 97,
      "retrieve_rerank": 177,
      "chat": 638,
      "follow_up_chat": 1864,
      "total": 2784
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 1258,
      "completion_tokens": 162,
      "total_tokens": 1420
    },
    "intent_router": {
      "prompt_tokens": 516,
      "completion_tokens": 54,
      "total_tokens": 570
    },
    "tool_rag": {
      "type": "usage",
      "chat": {
        "prompt_tokens": 319,
        "completion_tokens": 28,
        "total_tokens": 347
      },
      "follow_up_chat": {
        "prompt_tokens": 423,
        "completion_tokens": 80,
        "total_tokens": 503
      },
      "total": {
        "prompt_tokens": 742,
        "completion_tokens": 108,
        "total_tokens": 850
      }
    }
  },
  "status": {
    "ok": true,
    "state": "completed",
    "code": "ok"
  },
  "type": "done"
}
```

**Notes**

- Extra keys inside `usage.tool_rag` (e.g. `"type": "usage"`) are preserved when upstream sends them.
- Legacy flat **`route.route`** is `tool` for `user_profile` (eval gold may still say `rag`).

---

## Internal intent (`help`)

**Question:** *"what is AI llm?"*

```bash
curl -sS -X POST http://192.168.86.179:30184/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "what is AI llm?",
    "stream": true,
    "conversation_id": "conv-smoke-1"
  }'
```

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
      "type": "internal_intent",
      "intent": "help",
      "confidence": 1.0,
      "reason": "General knowledge about AI terminology",
      "source": "llm_router"
    },
    "rewrite": "what is ai llm?"
  },
  "stream": [
    {
      "type": "request_id",
      "session_id": "ses-123",
      "request_id": "req-123",
      "trace_id": "req-123",
      "conversation_id": "conv-smoke-1",
      "is_new_conversation": false
    },
    {
      "type": "rewrite",
      "text": "what is ai llm?"
    },
    {
      "type": "route",
      "route": "direct_reply",
      "route_detail": {
        "type": "internal_intent",
        "name": "help",
        "confidence": 1.0,
        "reason": "General knowledge about AI terminology"
      },
      "route_source": "llm_router",
      "text": "what is ai llm?"
    }
  ],
  "answer": {
    "text": "AI LLM refers to Artificial Intelligence Large Language Model, which is a type of machine learning model designed to understand and generate human-like text based on the input it receives.",
    "citations": []
  },
  "follow_up_questions": [],
  "latency_ms": {
    "total": 1809.68,
    "intent_router": {
      "total": 1808.07
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 512,
      "completion_tokens": 84,
      "total_tokens": 596
    },
    "intent_router": {
      "prompt_tokens": 512,
      "completion_tokens": 84,
      "total_tokens": 596
    }
  },
  "status": {
    "ok": true,
    "state": "completed",
    "code": "ok"
  },
  "type": "done"
}
```

**Question:** *"Hi"*

```bash
curl -sS -X POST http://192.168.86.179:30184/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "hi",
    "conversation_id": "conv-smoke-1"
  }'
```

```json
{
  "request": {
    "type": "request_id",
    "session_id": "ses-123",
    "request_id": "req-123",
    "trace_id": "req-123",
    "conversation_id": "conv-smoke-1",
    "is_new_conversation": false
  },
  "rewrite": {
    "type": "rewrite",
    "text": "hi?"
  },
  "route": {
    "type": "route",
    "route": "direct_reply",
    "route_detail": {
      "type": "internal_intent",
      "name": "greeting",
      "confidence": 0.99,
      "reason": "Matched greeting intent greeting_hi"
    },
    "route_source": "deterministic_rule",
    "text": "hi?"
  },
  "answer_delta": {
    "type": "answer_delta",
    "text": "Hello! How can I help you today with questions about Taixing Bi or your internal knowledge base?"
  },
  "latency_ms": {
    "total": 2.24,
    "intent_router": {
      "total": 0.83
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    }
  },
  "status": {
    "ok": true,
    "state": "completed",
    "code": "ok"
  },
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
      "type": "internal_intent",
      "intent": "greeting",
      "confidence": 0.99,
      "reason": "Matched greeting intent greeting_hi",
      "source": "deterministic_rule"
    },
    "rewrite": "hi?"
  }
}
```

