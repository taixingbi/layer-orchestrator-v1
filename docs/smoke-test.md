# Example: k3s / cluster access

Use the URL exposed by your Service (NodePort, LoadBalancer, or Ingress). Below uses a **NodePort** on a LAN host; replace the value with yours.

## Health

Pretty-print JSON (requires [`jq`](https://jqlang.github.io/jq/); omit `| jq .` for raw output):

```bash
curl -sS "http://192.168.86.179:30184/health" | jq .
```

## Readiness (LLM + RAG)

Returns `200` when both the chat-completions gateway and RAG HTTP service respond successfully; otherwise `503` with per-dependency details.

```bash
curl -sS "http://192.168.86.179:30184/ready" | jq .
```

Use `curl -i` or `curl -o /dev/null -w "%{http_code}\n"` if you need the HTTP status code (`200` vs `503`).

## Orchestrator (non-stream JSON)

Returns one aggregated JSON object. The pipeline uses a single **intent/rewrite router** LLM (`timings_ms.intent_router`), then either returns an immediate `answer` (routes `direct_reply`, `clarify`, `reject`) or runs RAG when `route` is `rag`. The `route` field is lowercase (`rag`, not `RAG`).

```bash
curl -sS -X POST "http://192.168.86.179:30184/orchestrator/answer" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-123" \
  -H "X-Trace-Id: req-123" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "what is taixing visa status in us?"
  }' | jq .
```

## Orchestrator with conversation `history` (follow-up question)

Prior turns are `user` / `assistant` pairs; the latest user message is `question`. The router uses history in one LLM call to produce a standalone `rewritten_question` and `route`; RAG runs only when `route` is `rag`.

```bash
curl -sS -X POST "http://192.168.86.179:30184/orchestrator/answer" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-124" \
  -H "X-Trace-Id: req-124" \
  -d '{
    "question": "What does he location?",
    "history": [
      {"role": "user", "content": "What is Taixing Bi US visa status?"},
      {"role": "assistant", "content": "Taixing has H4 EAD and does not need sponsorship."}
    ]
  }' | jq .
```

## Orchestrator (SSE with `stream=true`)

`-N` turns off curl buffering so Server-Sent Events stream line-by-line.  
`request_id`, `session_id`, and `trace_id` must be passed in headers (not request body).  
Optional user context (`X-User-Id`, `X-User-Roles`, `X-User-Groups`, `X-User-Teams`) is forwarded to the RAG service on `POST /v1/rag/query`.  
Expect `{"type":"state",...}` events during the RAG phase (`rag_query` only inside LangGraph); see [design.md](design.md). Successful streams end with `{"type":"answer",...}` (as soon as the graph returns), then phase states, then `{"type":"done"}`.

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/orchestrator/answer" \
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
    "stream": true
  }'
```

## RAG direct (SSE-capable endpoint)

Use this to isolate RAG behavior from orchestrator behavior.

```bash
curl -N -sS -X POST "http://192.168.86.179:30183/v1/rag/query" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "X-Request-Id: req-abc123" \
  -H "X-Session-Id: ses-xyz789" \
  -H "X-Trace-Id: trc-001" \
  -H "X-User-Id: taixing" \
  -H "X-User-Roles: hr" \
  -H "X-User-Groups: engineering" \
  -H "X-User-Teams: rag-platform" \
  -d '{
    "question": "what is taixing visa",
    "collection_base": "taixing_knowledge",
    "k": 5,
    "k_max": 40,
    "include_retrieval_hits": true
  }'
```


## Workflow safety limits

These protections are app-level safeguards (not gateway traffic shaping). Default env values:

- `MAX_REQUEST_BODY_MB=1`
- `MAX_HISTORY_MESSAGES=50` (recommended range: `30-50`)
- `MAX_QUESTION_CHARS=8000` (about 2k tokens)
- `MAX_CONTEXT_CHARS=120000`
- `REQUEST_TIMEOUT_MS=30000`
- `STREAM_IDLE_TIMEOUT_MS=30000`
- `MAX_CONCURRENT_DOWNSTREAM_CALLS=32`

### Oversized request body (`413`)

```bash
python3 - <<'PY'
import json
q = "x" * (7 * 1024)
with open("/tmp/orch_big.json", "w") as f:
    json.dump({"question": q}, f)
print("size bytes:", __import__("os").path.getsize("/tmp/orch_big.json"))
PY

curl --max-time 10 -sS -o /tmp/orch_413_body.json -w "HTTP %{http_code}\n" \
  -X POST "http://192.168.86.179:30184/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/orch_big.json

cat /tmp/orch_413_body.json
```

### History limit (`400`)

```bash
hist="$(jq -n '[range(0;51) | {role:"user", content:"hi"}]')"
json="$(jq -n --arg q "test" --argjson h "$hist" '{question: $q, history: $h}')"
curl -sS -o /tmp/orch_400_history.json -w "HTTP %{http_code}\n" \
  -X POST "http://192.168.86.179:30184/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data "$json"
cat /tmp/orch_400_history.json
```

### Context limit (`400`)

```bash
python3 - <<'PY'
import json, os

chunk = "x" * 3000
q = "x" * 1000

payload = {
    "question": q,
    "history": [
        {"role": "user", "content": chunk}
        for _ in range(40)
    ]
}

path = "/tmp/orch_context_big.json"
with open(path, "w") as f:
    json.dump(payload, f)

total_context_chars = len(q) + sum(len(m["content"]) for m in payload["history"])

print("file_size_bytes:", os.path.getsize(path))
print("question_chars:", len(q))
print("history_messages:", len(payload["history"]))
print("total_context_chars:", total_context_chars)
PY

curl --max-time 10 -sS -o /tmp/orch_400_context.json -w "HTTP %{http_code}\n" \
  -X POST "http://192.168.86.179:30184/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/orch_context_big.json

cat /tmp/orch_400_context.json
```

### Request timeout (`504`)

If total processing exceeds `REQUEST_TIMEOUT_MS`, non-stream responses return `504` with an error body; SSE responses emit a timeout error event and close.

## Feedback

`POST /feedback` records thumbs up/down on a prior answer. The handler always logs the event; it **forwards to LangSmith** only when `LANGCHAIN_API_KEY` or `LANGSMITH_API_KEY` is set and a run id is supplied. The server picks the LangSmith `run_id` in order: **`agent_graph_run_id`** (root graph run UUID from tracing, best match), **`trace_id`**, then **`request_id`**. LangSmith expects a real run UUID unless your project maps `trace_id` to that run.

**Thumbs up** (correlate with the same `trace_id` / `request_id` you used on `/orchestrator/answer`):

```bash
curl -sS -X POST "http://192.168.86.179:30184/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "req-123",
    "request_id": "req-123",
    "rating": "thumbs_up"
  }' | jq .
```

**Thumbs down** with optional `feedback_type` and `comment`:

```bash
curl -sS -X POST "http://192.168.86.179:30184/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "req-123",
    "rating": "thumbs_down",
    "feedback_type": "not_factual",
    "comment": "Answer did not match the cited policy",
    "question": "what is taixing visa status in us?"
  }' | jq .
```

`feedback_type` (optional): `not_relevant`, `biased`, `not_factual`, `incomplete_instructions`, `unsafe`, `style_tone`, `other`.

**With LangSmith root run id** (from a non-stream or SSE `answer` event when tracing is enabled):

```bash
curl -sS -X POST "http://192.168.86.179:30184/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_graph_run_id": "YOUR_LANGSMITH_ROOT_RUN_UUID",
    "rating": "thumbs_up"
  }' | jq .
```

## See also

- [Gateway inference](gateway-inference.md) — LLM base URL and headers
- [RAG query](rag-query.md) — RAG service used by the orchestrator
