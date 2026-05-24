# Response examples (`/orchestrator/answer`)

Full JSON envelopes for common tool routes. Same shape for **`stream: false`** and for SSE terminal **`done`** (append `"type": "done"` on stream only).

Schema reference: [schema-request-response.md](schema-request-response.md) (skeleton and field tables). Upstream MCP payloads: [schema-tool.md](schema-tool.md).

### Tool name ↔ timing / usage keys

| Orchestrator `meta.route.tool` / `meta.tool.name` | `meta.tool.type` | `meta.tool.key` (= `latency_ms` / `usage`) |
|---------------------------------------------------|------------------|---------------------------------------------|
| `user_profile` | `rag` | `tool_rag` |
| `github_search` | `github` | `tool_github_search` |
| `web_search` | `web` | `tool_tavily_search` |

---

## GitHub (`github_search`)

**Question:** *"in app of huntai, what is orchestrator design?"*

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

**Notes**

- `usage.tool_github_search` is upstream passthrough (empty `chat` is allowed).
- `usage.intent_router` is omitted when the router LLM did not run (deterministic GitHub short-circuit).

---

## RAG (`user_profile`)

**Question:** *"taixing visa status in us"*

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
      "confidence": 1.0
    },
    "tool": {
      "name": "user_profile",
      "type": "rag",
      "version": "v1",
      "key": "tool_rag"
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

**Notes**

- Extra keys inside `usage.tool_rag` (e.g. `"type": "usage"`) are preserved when upstream sends them.

---

## GitHub (extended smoke-test)

Same route as above; longer answer and citations.

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

  "answer": {
    "text": "- The orchestrator design is described in the README of layer-orchestrator-v1.\n- It acts as a FastAPI service handling HTTP chat completions and RAG queries.\n- Supports unified `/orchestrator/answer` endpoint for both chat and RAG requests.\n- Sends correlation IDs on headers for tracking requests.\n- Manages conversation IDs optionally passed in JSON bodies.\n- Calls the LLM gateway for completions and integrates with other components like RAG and embeddings.",

    "citations": [
      {
        "cite_id": 1,
        "source": "layer-mcp-github-v1 README",
        "text": "MCP server that answers natural-language questions about fixed GitHub repos."
      },
      {
        "cite_id": 2,
        "source": "layer-web-v1 README",
        "text": "Next.js 15 frontend with chat UI and BFF API routes."
      },
      {
        "cite_id": 3,
        "source": "layer-gateway-api-v1 README",
        "text": "FastAPI gateway for authentication, validation, tracing, and orchestrator access."
      },
      {
        "cite_id": 4,
        "source": "layer-orchestrator-v1 README",
        "text": "FastAPI orchestrator for chat completions, RAG, and unified SSE responses."
      },
      {
        "cite_id": 5,
        "source": "layer-rag-query-v1 README",
        "text": "Hybrid RAG retrieval using dense vectors, BM25, and RRF fusion."
      }
    ]
  },

  "follow_up_questions": [
    "What are the main responsibilities of the orchestrator?",
    "Can you explain how the orchestrator handles RAG queries?",
    "Which other components does the orchestrator integrate with?"
  ],

  "latency_ms": {
    "total": 8603.93,

    "intent_router": {
      "total": 1.02
    },

    "tool_github_search": {
      "retrieve_rerank": 4537,
      "chat": 3060,
      "follow_up_chat": 963,
      "total": 8586
    }
  },

  "usage": {
    "total": {
      "prompt_tokens": 302,
      "completion_tokens": 42,
      "total_tokens": 344
    },

    "tool_github_search": {
      "follow_up_chat": {
        "prompt_tokens": 302,
        "completion_tokens": 42,
        "total_tokens": 344
      },

      "total": {
        "prompt_tokens": 302,
        "completion_tokens": 42,
        "total_tokens": 344
      }
    }
  },

  "status": {
    "ok": true,
    "state": "completed"
  },

  "type": "done"
}
```

---

## Internal intent (`help`)

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
      "tool": "help",
      "confidence": 1.0,
      "reason": "General information about the location of the LLM agent."
    },

    "tool": {
      "name": "help",
      "type": "internal_intent",
      "version": "v1"
    },

    "rewrite": "location of llm agent"
  },

  "answer": {
    "text": "The LLM agent is located in the cloud and can be accessed through the application interface.",

    "citations": []
  },

  "follow_up_questions": [],

  "latency_ms": {
    "total": 1614.55,

    "intent_router": {
      "total": 1612.77
    }
  },

  "usage": {
    "total": {
      "prompt_tokens": 512,
      "completion_tokens": 73,
      "total_tokens": 585
    },

    "intent_router": {
      "prompt_tokens": 512,
      "completion_tokens": 73,
      "total_tokens": 585
    }
  },

  "status": {
    "ok": true,
    "state": "completed"
  },

  "type": "done"
}