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

## Metrics (Prometheus)

Use this for dashboards/alerts (request count, error rate, route count, p50/p95/p99, router/RAG latency, timeout count):

```bash
curl -sS "http://192.168.86.179:30184/metrics"
```

## Orchestrator (SSE)

Use `curl -N` and parse the final `{"type":"done",...}` event (or consume `rewrite` / `route` / `answer_delta` events). Correlation ids go in **headers**; optional **`conversation_id`** in the body. SSE does **not** include `{"type":"state",...}` (logs/metrics only). Internal intents (`greeting`, `help`, …) emit one `answer_delta` then `done`. The pipeline uses a single **intent/rewrite router** LLM unless a **server short-circuit** applies (see [intent-router.md](intent-router.md)), then either returns an immediate `answer` or runs a tool route.

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/v1/orchestrator/answer" \
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
    "conversation_id": "conv-smoke-1"
  }'
```

## Orchestrator with conversation `history` (follow-up question)

Prior turns are `user` / `assistant` pairs; the latest user message is `question`. The router uses history in one LLM call to produce a standalone `rewritten_question` and `route`; RAG runs only when `route` is `rag`.

```bash
curl -sS -X POST "http://192.168.86.179:30184/v1/orchestrator/answer" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-124" \
  -H "X-Trace-Id: req-124" \
  -d '{
    "question": "What does he location?",
    "conversation_id": "conv-smoke-1",
    "history": [
      {"role": "user", "content": "What is Taixing Bi US visa status?"},
      {"role": "assistant", "content": "Taixing has H4 EAD and does not need sponsorship."}
    ]
  }' | jq .
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

## Router eval only (no RAG call)

Use this to evaluate rewrite/route behavior and deterministic checks without running the RAG phase.

```bash
curl -sS -X POST "http://192.168.86.179:30184/v1/orchestrator/eval/router" \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: ses-123" \
  -H "X-Request-Id: req-router-1" \
  -H "X-Trace-Id: req-router-1" \
  -d '{
    "question": "What are the renewal requirements for H4 EAD?",
    "expected_route": "direct_reply",
    "conversation_id": "conv-router-eval-1",
    "router_model": "Qwen/Qwen2.5-7B-Instruct",
    "router_temperature": 0,
    "router_prompt_version": "router-v1.00",
    "history": [
      {"role": "user", "content": "What is Taixing Bi US visa status?"},
      {"role": "assistant", "content": "H4 EAD. No visa sponsorship required. [1]"}
    ]
  }' | jq .
```

The alternate router prompt `router-v1.01` is plain text in `app/prompts/router-v1.01.txt` (you can still pass `router_prompt_override` for an ad-hoc prompt). Default production file is `router-v1.00.txt` unless `ROUTER_PROMPT_VERSION` is set.

Response includes:

- Top-level `request_id`, `session_id`, `trace_id`, effective **`conversation_id`**, and **`is_new_conversation`**
- `router`: effective `model`, `temperature`, `prompt_version`, `prompt_source`, `prompt_file`, optional `prompt_fallback_from`, and `prompt_override_used`
- `decision`: router output (`rewritten_question`, `route`, `answer`, `reason`) — `answer` is the router’s inline text when present (e.g. `direct_reply` or clarify/reject messaging); for `rag` it is typically null until a full answer is produced downstream.
- `evaluation`: `expected_route`, `actual_route`, `route_match`, `all_checks_pass`, `checks` (including `route_match`), and `notes`


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
  -X POST "http://192.168.86.179:30184/v1/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/orch_big.json

cat /tmp/orch_413_body.json
```

### History limit (`400`)

```bash
hist="$(jq -n '[range(0;51) | {role:"user", content:"hi"}]')"
json="$(jq -n --arg q "test" --argjson h "$hist" '{question: $q, history: $h}')"
curl -sS -o /tmp/orch_400_history.json -w "HTTP %{http_code}\n" \
  -X POST "http://192.168.86.179:30184/v1/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data "$json"
cat /tmp/orch_400_history.json
```

### Context limit (`400`)

`MAX_CONTEXT_CHARS` applies to `len(question) + sum(history content) + len(conversation_id)` using the **effective** conversation id (including when the server assigns one because the body omitted or blanked it).

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
  -X POST "http://192.168.86.179:30184/v1/orchestrator/answer" \
  -H "Content-Type: application/json" \
  --data-binary @/tmp/orch_context_big.json

cat /tmp/orch_400_context.json
```

### Request timeout (`504`)

If total processing exceeds `REQUEST_TIMEOUT_MS`, SSE emits a timeout `error` event and closes.

## Feedback

`POST /v1/feedback` records thumbs up/down on a prior answer (always **SSE**; one `done` or `error` event). The handler always logs the event; it **forwards to LangSmith** only when `LANGCHAIN_API_KEY` or `LANGSMITH_API_KEY` is set and a run id is supplied. The server picks the LangSmith `run_id` in order: **`agent_graph_run_id`** (root graph run UUID from tracing, best match), **`trace_id`**, then **`request_id`**. LangSmith expects a real run UUID unless your project maps `trace_id` to that run.

**Thumbs up** (correlate with the same `trace_id` / `request_id` you used on `/v1/orchestrator/answer`):

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/v1/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "req-123",
    "request_id": "req-123",
    "rating": "thumbs_up"
  }' | jq .
```

**Thumbs down** with optional `feedback_type` and `comment`:

```bash
curl -N -sS -X POST "http://192.168.86.179:30184/v1/feedback" \
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
curl -N -sS -X POST "http://192.168.86.179:30184/v1/feedback" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_graph_run_id": "YOUR_LANGSMITH_ROOT_RUN_UUID",
    "rating": "thumbs_up"
  }' | jq .
```

## See also

- [Gateway inference](gateway-inference.md) — LLM base URL and headers
- [RAG query](rag-query.md) — RAG service used by the orchestrator
