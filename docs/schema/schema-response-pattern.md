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
      ".",
      " [",
      "1",
      "]"
    ],
    "merged_text": "Taixing Bi's visa status in the US is H4 EAD, and there is no visa sponsorship required. [1]"
  },
  "follow_up_questions": [
    "Can Taixing apply for a different type of visa in the future?",
    "What are the requirements for maintaining H4 EAD status?",
    "Is there any additional documentation needed to maintain H4 EAD status?"
  ],
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
    "total": 4988.74,
    "intent_router": {
      "total": 2255.62
    },
    "tool_rag": {
      "embed": 77,
      "retrieve_rerank": 151,
      "chat": 640,
      "follow_up_chat": 1848,
      "total": 2724
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
    "type": "answer",
    "answer": {
      "text": "- The orchestrator in the HuntAI application is designed to handle HTTP chat completions, RAG queries, and other AI tasks through the `layer-orchestrator-v1` repository [4]. It acts as a backend service that communicates with the LLM gateway for generating responses.\n- The orchestrator receives chat requests and processes them, generating responses that are returned to the frontend via the gateway [4].\n- It supports conversation IDs and correlation IDs for tracking requests, ensuring consistent handling across different calls [4].\n- The architecture includes components for handling requests, responses, and observability metrics, ensuring efficient and reliable processing [4].\n- The orchestrator is configured via environment variables, allowing for customization of behavior such as retries, timeouts, and circuit breaker thresholds [4].",
      "citations": [
        {
          "cite_id": 1,
          "source": "layer-mcp-github-v1 README",
          "text": "# layer-mcp-github\n\nMCP server (**[layer-mcp-github-v1](https://github.com/taixingbi/layer-mcp-github-v1)**) that answers natural-language questions about a fixed set of GitHub repos."
        },
        {
          "cite_id": 2,
          "source": "layer-web-v1 README",
          "text": "# HuntAI\n\n## Design\n\nFull technical design: docs/design.md"
        },
        {
          "cite_id": 3,
          "source": "layer-gateway-api-v1 README",
          "text": "# layer-gateway-api-v1\n\nFastAPI gateway that decouples Next.js from AI orchestration."
        },
        {
          "cite_id": 4,
          "source": "layer-orchestrator-v1 README",
          "text": "# layer-orchestrator-v1\n\nFastAPI service: HTTP chat completions via LLM gateway, HTTP RAG, and unified /orchestrator/answer endpoint."
        },
        {
          "cite_id": 5,
          "source": "layer-rag-query-v1 README",
          "text": "# layer-rag-query\n\nRAG hybrid retrieval: dense (vector) + BM25 + RRF fusion."
        },
        {
          "cite_id": 6,
          "source": "layer-gateway-inference-v1 README",
          "text": "# layer-gateway-inference-v1\n\nGPU-aware routing gateway for vLLM on k3s."
        },
        {
          "cite_id": 7,
          "source": "layer-gateway-embed-v1 README",
          "text": "# layer-gateway-embed-v1\n\nRequest-level routing gateway for /v1/embeddings."
        },
        {
          "cite_id": 8,
          "source": "layer-gateway-reranker-v1 README",
          "text": "# layer-gateway-reranker-v1\n\nRequest-level routing gateway for /v1/rerank."
        },
        {
          "cite_id": 9,
          "source": "layer-rag-ingest-v1 README",
          "text": "# RAG Ingest Pipeline\n\nPrepare chunk JSON files and upsert points into Qdrant."
        },
        {
          "cite_id": 10,
          "source": "k3s README",
          "text": "# k3s server + GPU agents\n\nManifests and scripts for k3s control plane and GPU workers."
        },
        {
          "cite_id": 11,
          "source": "layer-grafana-loki-central-logger README",
          "text": "# tb-loki-central-logger\n\nSend logs to Grafana Loki with httpx."
        }
      ]
    },
    "follow_up_questions": [
      "What specific APIs does the orchestrator use to communicate with the LLM gateway?",
      "Can you provide more details on how the orchestrator handles conversation IDs and correlation IDs?",
      "Are there any known issues or limitations with the current orchestrator design?"
    ],
    "usage": {
      "total": {
        "prompt_tokens": 358,
        "completion_tokens": 57,
        "total_tokens": 415
      },
      "tool_github_search": {
        "chat": {},
        "follow_up_chat": {
          "prompt_tokens": 358,
          "completion_tokens": 57,
          "total_tokens": 415
        },
        "total": {
          "prompt_tokens": 358,
          "completion_tokens": 57,
          "total_tokens": 415
        }
      }
    }
  },
  "done": {
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
      "total": 8230.47,
      "intent_router": {
        "total": 1.45
      },
      "tool_github_search": {
        "retrieve_rerank": 3590,
        "chat": 3360,
        "follow_up_chat": 1213,
        "total": 8171
      }
    },
    "status": {
      "ok": true,
      "state": "completed",
      "code": "ok"
    },
    "type": "done"
  }
}
```

---

## Internal intent (`help`)

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
echo


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
      "reason": "General knowledge about AI terminology",
      "source": "llm_router"
    },
    "rewrite": "what is ai llm?"
  },
  "latency_ms": {
    "total": 1742.95,
    "intent_router": {
      "total": 1741.4
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