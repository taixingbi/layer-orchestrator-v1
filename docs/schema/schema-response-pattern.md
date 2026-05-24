# Response examples (`/orchestrator/answer`)

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
curl -N -sS -X POST http://192.168.86.179:30184/orchestrator/answer \
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
  "answer": {
    "text": "- The orchestrator in HuntAI manages and routes requests to AI services.\n- HTTP chat completions, RAG, and unified `/orchestrator/answer` with SSE.\n- Correlation IDs, config via `app/config.py`, FastAPI entry in `app/main.py`.",
    "citations": [
      { "cite_id": 1, "source": "layer-mcp-github-v1 README" },
      { "cite_id": 4, "source": "layer-orchestrator-v1 README" }
    ]
  },
  "follow_up_questions": [
    "What specific backend services does the orchestrator call?",
    "Can you provide more details on how the orchestrator handles retries and timeouts?",
    "Where can I find environment configuration for the orchestrator?"
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
      "source": "deterministic_rule",
      "reason": "Deterministic: HuntAI/layer repo or gateway architecture question"
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
    "total": 8891.67,
    "intent_router": { "total": 0.42 },
    "tool_github_search": {
      "retrieve_rerank": 3493,
      "chat": 4303,
      "follow_up_chat": 1050,
      "total": 8855
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 406,
      "completion_tokens": 49,
      "total_tokens": 455
    },
    "tool_github_search": {
      "total": {
        "prompt_tokens": 406,
        "completion_tokens": 49,
        "total_tokens": 455
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
curl -N -sS -X POST http://192.168.86.179:30184/orchestrator/answer \
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
  "answer": {
    "text": "Taixing Bi's visa status in the US is H4 EAD, and there is no visa sponsorship required. [1]",
    "citations": [
      {
        "cite_id": 1,
        "chunk_id": "1607b45e-1c07-5c29-975d-bbf47ef3129c",
        "source": "personal_profile",
        "text": "Q: What is Taixing Bi's visa status / work authorization?\nA: H4 EAD. No visa sponsorship required."
      }
    ]
  },
  "stream": {
    "answer_delta_count": 27,
    "answer_delta_text": ["Ta", "ix", "ing", " Bi", "'s", " visa", " status", " in", " the", " US", " is", " H", "4", " E", "AD", ",", " and", " there", " is", " no", " visa", " sponsorship", " required", ".", " [", "1", "]"],
    "merged_text": "Taixing Bi's visa status in the US is H4 EAD, and there is no visa sponsorship required. [1]"
  },
  "follow_up_questions": [
    "Can Taixing apply for a different type of visa in the future?",
    "What are the requirements for maintaining H4 EAD status?",
    "Is there any additional documentation needed to maintain H4 EAD status?"
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
      "source": "llm_router",
      "reason": "Needs Taixing Bi-specific facts"
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
    "total": 4988.74,
    "intent_router": { "total": 2255.62 },
    "tool_rag": {
      "embed": 77,
      "retrieve_rerank": 151,
      "chat": 640,
      "follow_up_chat": 1848,
      "total": 2724
    }
  },
  "usage": {
    "total": {
      "prompt_tokens": 1258,
      "completion_tokens": 165,
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
        "completion_tokens": 28,
        "total_tokens": 347
      },
      "follow_up_chat": {
        "prompt_tokens": 423,
        "completion_tokens": 83,
        "total_tokens": 506
      },
      "total": {
        "prompt_tokens": 742,
        "completion_tokens": 111,
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
curl -sS -X POST http://192.168.86.179:30184/orchestrator/answer \
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
