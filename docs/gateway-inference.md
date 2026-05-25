# Gateway inference (chat completions)

The orchestrator calls your LLM over **HTTP** using the common **`POST {base}/v1/chat/completions`** JSON shape. The implementation uses LangChain’s HTTP chat client (from the `langchain-openai` package) to serialize requests and parse responses; your server does not need to be any particular vendor.

## Configure the orchestrator

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_GATEWAY_BASE_URL` | **Yes** | Origin of the inference service, with or without a `/v1` suffix (the app normalizes to `…/v1`). Example: `http://192.168.86.179:30180` |
| `LLM_MODEL` | No | Model id in the JSON body (default: `Qwen/Qwen2.5-7B-Instruct`) |
| `LLM_API_KEY` | No | If your gateway checks `Authorization`, set a real secret. Otherwise omit it; the client sends a placeholder the server can ignore. |

### Example `.env` snippet

```env
LLM_GATEWAY_BASE_URL=http://192.168.86.179:30180
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

## Request headers (orchestrator → gateway)

Chat calls may include:

- `X-Request-Id`
- `X-Session-Id`
- `X-Trace-Id` (defaults to the request id when not set separately)
- `X-Conversation-Id` (effective thread id when the client supplied one or the orchestrator assigned `conv_<uuidhex>`)
- `X-Is-New-Conversation` (`true` or `false` when `X-Conversation-Id` is sent; indicates whether the orchestrator minted a new id on this request)

Values come from the incoming HTTP request when provided (e.g. `/v1/orchestrator/answer`). The gateway may ignore or log them.

## Sanity check with `curl`

```bash
curl -N http://192.168.86.179:30180/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: request-id-1" \
  -H "X-Trace-Id: trace-id-1" \
  -H "X-Session-Id: session-id-1" \
  -d '{
    "model": "Qwen/Qwen2.5-7B-Instruct",
    "messages": [
      {"role": "user", "content": "where is jersey city"}
    ],
    "max_tokens": 50,
    "temperature": 0.7,
    "stream": true
  }'
```

If this works, use the same host and model in `LLM_GATEWAY_BASE_URL` and `LLM_MODEL`. The **intent router** uses **non-streaming** chat completions. The legacy LangGraph code under `app/graph/` used tool calling; the **default pipeline** does not invoke that graph.

## Tool calling (legacy graph only)

The compiled LangGraph agent in `app/graph/` used **`bind_tools`**. That path is **not** used by `app/core/pipeline.py`. Production RAG runs via direct HTTP (`app/clients/rag_http.py`) or MCP (`USE_MCP_TOOLS=true`).

## See also

- [README.md](../README.md) — full environment table and run instructions.
