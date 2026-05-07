# Example: k3s / cluster access

Use the URL exposed by your Service (NodePort, LoadBalancer, or Ingress). Below uses a **NodePort** on a LAN host; replace the value with yours.

```bash
export ORCHESTRATOR_URL="http://192.168.86.179:30184"
```

## Health

Pretty-print JSON (requires [`jq`](https://jqlang.github.io/jq/); omit `| jq .` for raw output):

```bash
curl -sS "${ORCHESTRATOR_URL}/health" | jq .
```

## Orchestrator SSE (`stream-answer`)

`-N` turns off curl buffering so Server-Sent Events stream line-by-line.

```bash
curl -N -sS -X POST "${ORCHESTRATOR_URL}/orchestrator/stream-answer" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "ses-123",
    "request_id": "req-123",
    "question": "what is taixing visa status?"
  }'
```

## See also

- [Gateway inference](gateway-inference.md) — LLM base URL and headers
- [RAG query](rag-query.md) — RAG service used by the orchestrator
