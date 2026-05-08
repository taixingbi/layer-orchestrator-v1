# Example: k3s / cluster access

Use the URL exposed by your Service (NodePort, LoadBalancer, or Ingress). Below uses a **NodePort** on a LAN host; replace the value with yours.

## Health

Pretty-print JSON (requires [`jq`](https://jqlang.github.io/jq/); omit `| jq .` for raw output):

```bash
curl -sS "http://192.168.86.179:30184/health" | jq .
```

## Orchestrator SSE (`stream-answer`)

`-N` turns off curl buffering so Server-Sent Events stream line-by-line.  
`request_id`, `session_id`, and `trace_id` must be passed in headers (not request body).

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/orchestrator/stream-answer" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -d '{
    "question": "what is taixing visa status in us?"
  }'
```

## RAG query direct smoke test (SSE-capable)

Use this to validate `layer-rag-query` directly. The orchestrator now calls this endpoint with
the same correlation headers and accepts SSE responses.

```bash
curl -N -sS -X POST "http://192.168.86.179:30183/v1/rag/query" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: req-abc123" \
  -H "X-Session-Id: ses-xyz789" \
  -H "X-Trace-Id: trc-001" \
  -d '{
    "question": "what is taixing visa",
    "collection_base": "taixing_knowledge",
    "k": 5,
    "k_max": 40,
    "include_retrieval_hits": true
  }'
```

## See also

- [Gateway inference](gateway-inference.md) — LLM base URL and headers
- [RAG query](rag-query.md) — RAG service used by the orchestrator
