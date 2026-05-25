# Response examples (`/v1/orchestrator/answer`)

Full JSON envelopes for common routes. **Terminal** `done` / `error` matches **`stream: false`** body shape (plus `"type": "done"` or `"type": "error"` on stream).

Schema reference: [schema-request-response.md](schema-request-response.md). Upstream MCP payloads: [schema-tool.md](schema-tool.md).

### Tool name ↔ timing / usage keys

| Orchestrator `meta.route.tool` / `meta.tool.name` | `meta.tool.type` | `meta.tool.key` (= `latency_ms` / `usage`) |
|---------------------------------------------------|------------------|---------------------------------------------|
| `user_profile` | `rag` | `tool_rag` |
| `github_search` | `github` | `tool_github_search` |
| `web_search` | `web` | `tool_tavily_search` |

### Stream vs `done`

During **`stream: true`**, the server emits separate SSE events: `request_id` → `rewrite` → **`route`** → optional `answer_delta` → `answer` → **`done`**.

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
    "text": "in app of huntai, what is orchestrator design?"
  },

  "route": {
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
  },

  "stream": {
    "answer_delta_count": 124,

    "merged_text": "- The orchestrator in HuntAI is designed to manage and route requests to various AI services such as chat completions, embeddings, and reranking [4].\n- It supports HTTP chat completions, RAG queries, and a unified `/v1/orchestrator/answer` endpoint for both streaming and non-streaming responses [4].\n- The architecture involves a FastAPI service that handles requests, applies load-aware routing, and communicates with backend services like vLLM for inference [4].\n- The orchestrator uses correlation IDs for tracking requests and supports optional conversation IDs for reranking tasks [4].\n- Detailed documentation for the request and response schema is available in the repository [4]."
  },

  "answer": {
    "text": "- The orchestrator in HuntAI is designed to manage and route requests to various AI services such as chat completions, embeddings, and reranking [4].\n- It supports HTTP chat completions, RAG queries, and a unified `/v1/orchestrator/answer` endpoint for both streaming and non-streaming responses [4].\n- The architecture involves a FastAPI service that handles requests, applies load-aware routing, and communicates with backend services like vLLM for inference [4].\n- The orchestrator uses correlation IDs for tracking requests and supports optional conversation IDs for reranking tasks [4].\n- Detailed documentation for the request and response schema is available in the repository [4].",

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
    "What specific backend services does the orchestrator communicate with?",
    "Can you provide more details on how the orchestrator applies load-aware routing?",
    "Is there any particular tool or library used for managing correlation IDs in the orchestrator?"
  ],

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

  "latency_ms": {
    "total": 8071.24,

    "intent_router": {
      "total": 1.55
    },

    "tool_github_search": {
      "retrieve_rerank": 3970,
      "chat": 2897,
      "follow_up_chat": 1138,
      "total": 8013
    }
  },

  "usage": {
    "total": {
      "prompt_tokens": 338,
      "completion_tokens": 53,
      "total_tokens": 391
    },

    "tool_github_search": {
      "total": {
        "prompt_tokens": 338,
        "completion_tokens": 53,
        "total_tokens": 391
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
    "stream": true,
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
    "text": "taixing visa status in us"
  },
  "route": {
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
  },
  "stream": {
    "answer_delta_count": 26,
    "answer_delta_text": [
      "Ta",
      "ix",
      "ing",
      " Bi",
      "'s",
      " visa",
      " status",
      " in",
      " the",
      " US",
      " is",
      " H",
      "4",
      " E",
      "AD",
      ",",
      " and",
      " there",
      " is",
      " no",
      " visa",
      " sponsorship",
      " required",
      " [",
      "1",
      "]."
    ],
    "merged_text": "Taixing Bi's visa status in the US is H4 EAD, and there is no visa sponsorship required [1]."
  },
  "answer": {
    "text": "Taixing Bi's visa status in the US is H4 EAD, and there is no visa sponsorship required [1].",
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
    "Can Taixing apply for a different type of visa?",
    "Are there any restrictions on Taixing's job search while holding an H4 EAD?",
    "What are the next steps for Taixing to use the H4 EAD for employment?"
  ],
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
  "latency_ms": {
    "total": 4893.61,
    "intent_router": {
      "total": 2018.53
    },
    "tool_rag": {
      "embed": 86,
      "retrieve_rerank": 154,
      "chat": 620,
      "follow_up_chat": 1988,
      "total": 2856
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 1257,
      "completion_tokens": 166,
      "total_tokens": 1423
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
        "completion_tokens": 27,
        "total_tokens": 346
      },
      "follow_up_chat": {
        "prompt_tokens": 422,
        "completion_tokens": 85,
        "total_tokens": 507
      },
      "total": {
        "prompt_tokens": 741,
        "completion_tokens": 112,
        "total_tokens": 853
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
    "text": "what is ai llm?"
  },
  "route": {
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
  },
  "answer": {
    "text": "AI LLM refers to Artificial Intelligence Large Language Model, which is a type of machine learning model designed to understand and generate human-like text based on the input it receives.",
    "citations": []
  },
  "follow_up_questions": [],
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
      "source": "llm_router",
      "reason": "General knowledge about AI terminology"
    },
    "rewrite": "what is ai llm?"
  },
  "latency_ms": {
    "total": 1742.95,
    "intent_router": { "total": 1741.4 }
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

**Notes**

- No **`meta.tool`** on internal intents (no tool was invoked).
- **`route.route_detail.name`** is the intent id; **`meta.route.intent`** mirrors it on `done`.
