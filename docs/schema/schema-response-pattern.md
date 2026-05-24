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
    "state": "completed",
    "code": "ok"
  }
}
```

**Notes**

- `usage.tool_github_search` is upstream passthrough (empty `chat` is allowed).
- `usage.intent_router` is omitted when the router LLM did not run (deterministic GitHub short-circuit).

---

## RAG (`user_profile`)

**Question:** *"taixing visa status in us"*
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
  }


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
    "Can Taixing switch to another visa type in the future?",
    "What are the requirements for maintaining H4 EAD status?",
    "Are there any restrictions on working hours or types of work with H4 EAD?"
  ],

  "latency_ms": {
    "total": 5028.25,

    "intent_router": {
      "total": 2132.04
    },

    "tool_rag": {
      "embed": 238,
      "retrieve_rerank": 204,
      "chat": 648,
      "follow_up_chat": 1768,
      "total": 2865
    }
  },

  "usage": {
    "total": {
      "prompt_tokens": 1258,
      "completion_tokens": 158,
      "total_tokens": 1416
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
        "completion_tokens": 76,
        "total_tokens": 499
      },

      "total": {
        "prompt_tokens": 742,
        "completion_tokens": 104,
        "total_tokens": 846
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

---

## GitHub (extended smoke-test)

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
    "question": "in app of huntai, what is orchestrator design?",
    "stream": true,
    "conversation_id": "conv-smoke-1"
  }'
echo


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

  "answer": {
    "text": "- The orchestrator design in the HuntAI application is described in the README of the `layer-orchestrator-v1` repository [4].\n- It acts as a FastAPI service handling HTTP chat completions, RAG, and unified `/orchestrator/answer` endpoints.\n- Supports streaming responses via SSE.\n- Handles correlation IDs in headers for traceability.\n- Routes requests to the appropriate backend based on configuration and current load conditions.",

    "citations": [
      {
        "cite_id": 1,
        "source": "layer-mcp-github-v1 README",
        "text": "MCP server that answers natural-language questions about a fixed set of GitHub repos."
      },
      {
        "cite_id": 2,
        "source": "layer-web-v1 README",
        "text": "Next.js 15 frontend with chat UI and BFF API routes."
      },
      {
        "cite_id": 3,
        "source": "layer-gateway-api-v1 README",
        "text": "FastAPI gateway that decouples Next.js from AI orchestration."
      },
      {
        "cite_id": 4,
        "source": "layer-orchestrator-v1 README",
        "text": "FastAPI service for HTTP chat completions, HTTP RAG, and unified `/orchestrator/answer` endpoints with SSE support."
      },
      {
        "cite_id": 5,
        "source": "layer-rag-query-v1 README",
        "text": "RAG hybrid retrieval using dense vectors, BM25, and RRF fusion."
      },
      {
        "cite_id": 6,
        "source": "layer-gateway-inference-v1 README",
        "text": "GPU-aware routing gateway for vLLM inference workloads."
      },
      {
        "cite_id": 7,
        "source": "layer-gateway-embed-v1 README",
        "text": "Request-level routing gateway for `/v1/embeddings` across multiple vLLM backends."
      },
      {
        "cite_id": 8,
        "source": "layer-gateway-reranker-v1 README",
        "text": "Request-level routing gateway for `/v1/rerank` across multiple vLLM backends."
      },
      {
        "cite_id": 9,
        "source": "layer-rag-ingest-v1 README",
        "text": "Prepare chunks, enrich metadata, embed text, and upsert points into Qdrant."
      },
      {
        "cite_id": 10,
        "source": "k3s README",
        "text": "k3s control plane and GPU worker manifests/scripts."
      },
      {
        "cite_id": 11,
        "source": "layer-grafana-loki-central-logger README",
        "text": "Send logs to Grafana Loki with async httpx-based logging."
      }
    ]
  },

  "follow_up_questions": [
    "What are the main components of the orchestrator in the layer-orchestrator-v1 repository?",
    "How does the orchestrator handle error scenarios?",
    "Can you explain the role of correlation IDs in the orchestrator's design?"
  ],

  "latency_ms": {
    "total": 7466.06,

    "intent_router": {
      "total": 0.98
    },

    "tool_github_search": {
      "retrieve_rerank": 3795,
      "chat": 2536,
      "follow_up_chat": 1116,
      "total": 7456
    }
  },

  "usage": {
    "total": {
      "prompt_tokens": 292,
      "completion_tokens": 54,
      "total_tokens": 346
    },

    "tool_github_search": {
      "follow_up_chat": {
        "prompt_tokens": 292,
        "completion_tokens": 54,
        "total_tokens": 346
      },

      "total": {
        "prompt_tokens": 292,
        "completion_tokens": 54,
        "total_tokens": 346
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
      "intent": "help",
      "confidence": 1.0,
      "source": "llm_router",
      "reason": "General information about the location of the LLM agent."
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
    "state": "completed",
    "code": "ok"
  },

  "type": "done"
}