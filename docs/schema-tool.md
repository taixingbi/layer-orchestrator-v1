# Tool response schema (MCP / upstream)

JSON shape returned by **MCP tool services** (`rag_query`, `ask_repo`) on the terminal **`done`** event (or equivalent JSON body). The orchestrator normalizes this into [`/orchestrator/answer`](schema-request-response.md) — see [Mapping to orchestrator](#mapping-to-orchestrator) below.

---

## Top-level fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `meta` | object | yes | Correlation ids, user relay, tool identity; optional provider blocks (`rag`, `github`, …) |
| `answer` | object | yes | `text` plus optional `citations` |
| `follow_up_questions` | string[] | no | Suggested follow-ups |
| `latency_ms` | object | no | Phase timings in milliseconds; must include `total` when present |
| `usage` | object | no | Token usage by phase (`chat`, `follow_up_chat`, `total`, …) |
| `status` | object | no | `{ "ok": boolean, "state": "completed" \| … }` |

### `meta`

| Field | Type | Description |
|-------|------|-------------|
| `request_id` | string | Echo of `X-Request-Id` |
| `session_id` | string | Echo of `X-Session-Id` |
| `trace_id` | string | Echo of `X-Trace-Id` |
| `conversation_id` | string | Thread id |
| `user` | object | `id`, `roles`, `groups`, `teams` (strings) |
| `tool` | object | `name` (orchestrator tool id), `type`, optional `version` |
| `rag` | object | RAG-only: `collection`, `k`, `k_max`, … |
| `github` | object | GitHub-only: `repos` (string[]) |

### `answer`

| Field | Type | Description |
|-------|------|-------------|
| `text` | string | User-visible answer (may include inline cite markers `[1]`) |
| `citations` | object[] | Provider-specific; common keys: `cite_id`, `source`, `text`, `chunk_id`, `repo`, `url` |

### `latency_ms` / `usage`

Opaque phase-keyed objects. The orchestrator **passthroughs them unchanged** under:

| Tool `meta.tool.name` | Orchestrator `latency_ms` / `usage` key |
|-----------------------|---------------------------------------|
| `user_profile` | `tool_rag` |
| `github_repo_search` | `tool_github_search` |

---

## Mapping to orchestrator client envelope

| Upstream ([schema-tool.md](schema-tool.md)) | Client [`/orchestrator/answer`](schema-request-response.md) |
|---------------------------------------------|-------------------------------------------------------------|
| `meta` (correlation, user, tool) | `meta` (plus orchestrator `route`, `rewrite`) |
| `answer.text` | `answer.text` |
| `answer.citations` | `answer.citations` |
| `follow_up_questions` | `follow_up_questions` |
| `latency_ms` | `latency_ms.tool_rag` or `latency_ms.tool_github_search` |
| `usage` | `usage.tool_rag` or `usage.tool_github_search` |
| `status` | `status` on upstream only; client `status` is orchestrator-wide |

Orchestrator adds `latency_ms.intent_router`, `usage.intent_router`, `usage.total`, and `latency_ms.total`.

---

## Canonical pattern (skeleton)

```json
{
  "meta": {
    "request_id": "string",
    "session_id": "string",
    "trace_id": "string",
    "conversation_id": "string",
    "user": {
      "id": "string",
      "roles": "string",
      "groups": "string",
      "teams": "string"
    },
    "tool": {
      "name": "user_profile | github_repo_search",
      "type": "rag | github",
      "version": "v1"
    }
  },
  "answer": {
    "text": "string",
    "citations": [
      {
        "cite_id": 1,
        "source": "string",
        "text": "string"
      }
    ]
  },
  "follow_up_questions": ["string"],
  "latency_ms": {
    "phase_name": 0,
    "total": 0
  },
  "usage": {
    "chat": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    },
    "total": {
      "prompt_tokens": 0,
      "completion_tokens": 0,
      "total_tokens": 0
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

Provider-specific keys under `meta` (e.g. `rag`, `github`) are optional extensions.

---

## Example: MCP RAG (`user_profile` / `rag_query`)

```json
{
  "meta": {
    "request_id": "req-abc123",
    "session_id": "ses-xyz789",
    "trace_id": "trc-001",
    "conversation_id": "conv_rag_1",
    "user": {
      "id": "taixing",
      "roles": "hr",
      "groups": "engineering",
      "teams": "rag-platform"
    },
    "tool": {
      "name": "user_profile",
      "type": "rag"
    },
    "rag": {
      "collection": "taixing_knowledge",
      "k": 5,
      "k_max": 50
    }
  },
  "answer": {
    "text": "Taixing Bi's visa status is H4 EAD, and there is no visa sponsorship required. [1]",
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
    "What does H4 EAD mean for work authorization?",
    "Are there any restrictions with H4 EAD?",
    "Does Taixing need visa sponsorship?"
  ],
  "latency_ms": {
    "embed": 92,
    "retrieve_rerank": 204,
    "chat": 619,
    "follow_up_chat": 2143,
    "total": 3061
  },
  "usage": {
    "chat": {
      "prompt_tokens": 328,
      "completion_tokens": 25,
      "total_tokens": 353
    },
    "follow_up_chat": {
      "prompt_tokens": 429,
      "completion_tokens": 93,
      "total_tokens": 522
    },
    "total": {
      "prompt_tokens": 757,
      "completion_tokens": 118,
      "total_tokens": 875
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

**Orchestrator client** uses the same nested envelope; tool phases appear under `latency_ms.tool_rag` and `usage.tool_rag` (see [schema-request-response.md](schema-request-response.md)).

---

## Example: MCP GitHub (`github_repo_search` / `ask_repo`)

```json
{
  "meta": {
    "request_id": "req-github-123",
    "session_id": "ses-github-789",
    "trace_id": "trc-github-001",
    "conversation_id": "conv_github_1",
    "user": {
      "id": "taixing",
      "roles": "engineering",
      "groups": "engineering",
      "teams": "rag-platform"
    },
    "tool": {
      "name": "github_repo_search",
      "type": "github"
    },
    "github": {
      "repos": [
        "taixingbi/layer-orchestrator-v1",
        "taixingbi/layer-gateway-api-v1"
      ]
    }
  },
  "answer": {
    "text": "The HuntAI architecture uses a frontend, gateway API, orchestrator, RAG query service, and model gateways. The gateway handles authentication and request normalization, while the orchestrator routes requests to RAG or chat backends. [1] [2]",
    "citations": [
      {
        "cite_id": 1,
        "repo": "taixingbi/layer-gateway-api-v1",
        "source": "README",
        "url": "https://github.com/taixingbi/layer-gateway-api-v1",
        "text": "FastAPI gateway for authentication, request normalization, and orchestrator access."
      },
      {
        "cite_id": 2,
        "repo": "taixingbi/layer-orchestrator-v1",
        "source": "README",
        "url": "https://github.com/taixingbi/layer-orchestrator-v1",
        "text": "FastAPI orchestration service for chat completions and RAG capabilities."
      }
    ]
  },
  "follow_up_questions": [
    "How does the gateway call the orchestrator?",
    "How does the orchestrator choose RAG vs chat?",
    "How should tracing IDs flow across services?"
  ],
  "latency_ms": {
    "github_readme": 2693,
    "github_search": 1335,
    "chat": 8349,
    "follow_up_chat": 1479,
    "total": 13886
  },
  "usage": {
    "chat": {
      "prompt_tokens": 558,
      "completion_tokens": 120,
      "total_tokens": 678
    },
    "follow_up_chat": {
      "prompt_tokens": 558,
      "completion_tokens": 66,
      "total_tokens": 624
    },
    "total": {
      "prompt_tokens": 1116,
      "completion_tokens": 186,
      "total_tokens": 1302
    }
  },
  "status": {
    "ok": true,
    "state": "completed"
  }
}
```

**Orchestrator client** uses `latency_ms.tool_github_search` and `usage.tool_github_search` passthrough.

---

## Streaming note

MCP may emit **`event: delta`** before **`event: done`**. The orchestrator forwards deltas as SSE `answer_delta` and maps the terminal payload into the client envelope on `answer` and `done`. See [schema-request-response.md — stream](schema-request-response.md#post-orchestratoranswer--stream-stream-true).
