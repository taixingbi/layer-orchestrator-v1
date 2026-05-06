# RAG query (HTTP API)

When **`RAG_HTTP_BASE_URL`** is set, the orchestrator uses a **REST** RAG service instead of MCP. The app calls:

```http
POST {RAG_HTTP_BASE_URL}/v1/rag/query
Content-Type: application/json
```

The LangGraph agent exposes this as the tool **`query_knowledge_base`** (see `app/rag_http_tool.py`). `request_id` and `session_id` are injected from the orchestrator context when present.

## Environment variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `RAG_HTTP_BASE_URL` | Yes (for HTTP RAG) | — | Service origin only (no path). Example: `http://192.168.86.179:30183` |
| `RAG_COLLECTION_BASE` | No | `taixing_knowledge` | `collection_base` in the JSON body |
| `RAG_K` | No | `5` | Retrieval `k` |
| `RAG_K_MAX` | No | `40` | Upper cap `k_max` |
| `RAG_INCLUDE_RETRIEVAL_HITS` | No | `true` | Whether to ask for hits in the response |
| `TOOLS_TIMEOUT_S` | No | `60` | HTTP client timeout for this request (seconds) |

If **`RAG_HTTP_BASE_URL`** is unset, you can point **`MCP_TOOL_RAG_URL`** at an MCP HTTP server instead (see [README.md](../README.md)); the HTTP path above is not used in that mode.

### Example `.env` snippet

```env
RAG_HTTP_BASE_URL=http://192.168.86.179:30183
RAG_COLLECTION_BASE=taixing_knowledge
```

## Request body (JSON)

The orchestrator sends:

| Field | Type | Notes |
|-------|------|--------|
| `question` | string | From the agent / user (after optional rewrite) |
| `collection_base` | string | From `RAG_COLLECTION_BASE` |
| `request_id` | string | From client context, or `"unknown"` |
| `session_id` | string | From client context, or `"unknown"` |
| `k` | int | From `RAG_K` |
| `k_max` | int | From `RAG_K_MAX` |
| `include_retrieval_hits` | bool | From `RAG_INCLUDE_RETRIEVAL_HITS` |

## Example `curl`

```bash
curl -sS -X POST http://192.168.86.179:30183/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Can Taixing work for any US company with an H4 EAD, or are there restrictions?",
    "collection_base": "taixing_knowledge",
    "request_id": "req-abc123",
    "session_id": "ses-xyz789",
    "k": 5,
    "k_max": 40,
    "include_retrieval_hits": true
  }' | jq .
```

Adjust host, port, and `collection_base` to match your deployment.

## Response shape (orchestrator behavior)

The tool accepts normal JSON from your service. For the LLM it prefers, in order:

- Top-level string fields: `answer`, `response`, `generated_answer`, `text`
- `retrieval_hits` or `hits` (included in the tool result when present)

If none of those match, the **full JSON** is stringified (capped in length) so the model still sees the payload.

## See also

- [README.md](../README.md) — full environment table and run instructions.
- [Gateway inference](gateway-inference.md) — LLM side (`/v1/chat/completions`).
