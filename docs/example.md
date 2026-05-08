# Example: k3s / cluster access

Use the URL exposed by your Service (NodePort, LoadBalancer, or Ingress). Below uses a **NodePort** on a LAN host; replace the value with yours.

## Health

Pretty-print JSON (requires [`jq`](https://jqlang.github.io/jq/); omit `| jq .` for raw output):

```bash
curl -sS "http://192.168.86.179:30184/health" | jq .
```

## Orchestrator SSE (`stream-answer`)

`-N` turns off curl buffering so Server-Sent Events stream line-by-line.  
Set correlation IDs in headers so logs use the same values as the request.

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/orchestrator/stream-answer" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -d '{
    "question": "what is taixing visa status?"
  }'
```

## See also

- [Gateway inference](gateway-inference.md) — LLM base URL and headers
- [RAG query](rag-query.md) — RAG service used by the orchestrator
