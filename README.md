# layer-orchestrator-v1

## FastAPI Orchestrator

FastAPI service: **HTTP chat completions** via `LLM_GATEWAY_BASE_URL` (`POST …/v1/chat/completions`), **HTTP RAG**, and unified **`POST /v1/orchestrator/answer`** (`stream` default **true** → SSE with **`answer_delta`**; `stream: false` → JSON). **`POST /v1/feedback`** is SSE; **`POST /v1/orchestrator/eval/router`** is JSON only. Send correlation ids on headers (`X-Request-Id`, `X-Session-Id`, `X-Trace-Id`). Optional **`conversation_id`** may be sent in the **`/v1/orchestrator/answer`** and **`/v1/orchestrator/eval/router`** JSON body; if omitted or blank, the server assigns `conv_<uuidhex>` and returns **`is_new_conversation`: true**. See [schema-request-response.md](docs/schema/schema-request-response.md).

## Layout

- **`app/main.py`** — FastAPI entrypoint
- **`app/config.py`** — settings from environment
- **`app/api/`** — HTTP route handlers
- **`app/core/`** — pipeline, router, rewrite, SSE, state
- **`app/clients/`** — outbound RAG HTTP and readiness probes
- **`app/graph/`** — legacy LangGraph (unused by default pipeline)
- **`app/observability/`** — logging, request context, metrics, usage, feedback
- **`app/intents/`**, **`app/tools/`**, **`app/schemas/`**, **`app/prompts/`**

## Documentation

- [Request & response schema](docs/schema/schema-request-response.md) — JSON bodies, headers, `/v1/orchestrator/answer`, `/v1/orchestrator/eval/router`, SSE events, limits, `conversation_id`, and `is_new_conversation`.
- [Response examples](docs/schema/schema-response-examples.md) — full GitHub and RAG smoke-test JSON envelopes.
- [Conversation id](docs/conversation-id.md) — threading, resolution, logs, and propagation to gateway + RAG.
- [Gateway inference](docs/gateway-inference.md) — chat completions URL, model, headers, `curl` example, and tool-calling note.
- [RAG query](docs/rag-query.md) — HTTP RAG `POST /v1/rag/query`, env vars, request body, and `curl` example.
- [Small-talk seed](docs/smalltalk-seed.md) — `app/prompts/seed_intents/*.json`, empty-history exact match then regex patterns (answers from JSON), no router LLM on hit.
- [Intent router](docs/intent-router.md) — rewrite + route pipeline, injection guard, small-talk short-circuit, LLM path, post-processing, and prompt assets.
- [Design](docs/design.md) — architecture, request flows, reliability loop, and trade-offs.
- [Architecture flow](docs/architecture.md) — SSE sequence, tool dispatch, and sequence diagram.
- [Smoke / cluster examples](docs/smoke-test.md) — health, orchestrator `curl`, limits, and eval snippets.
- [Gold router eval](gold-test/readme.md) — batch CSV tests for `/v1/orchestrator/eval/router` (optional CI / local harness).
- [Router DPO dataset](dpo-router/README.md) — build `train.jsonl` / `val.jsonl` from gold CSVs; train in [layer-router-dpo-v1](../layer-router-dpo-v1/README.md).

## Setup

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install .
# optional dev deps:
# pip install ".[dev]"
```

## Environment (.env)

Copy or create `.env` at the **project root** (loaded by `app/config.py`). Typical groups: app, LLM, RAG, LangSmith, logging.

| Variable | Description |
|----------|-------------|
| `APP_NAME` | Application name (default: `layer-orchestrator-v1`) |
| `APP_VERSION` | App version string (in CI images this is injected from workflow tag/input; local fallback resolves to package metadata or `dev`) |
| `LLM_GATEWAY_BASE_URL` | **Required.** Inference service origin; `/v1` is appended if missing (e.g. `http://host:30180`) |
| `LLM_MODEL` | Chat model id sent in the completion request (default: `Qwen/Qwen2.5-7B-Instruct`) |
| `LLM_API_KEY` | Optional; set if the gateway validates `Authorization` (otherwise a placeholder is sent) |
| `RAG_HTTP_BASE_URL` | RAG service base URL; app calls `POST {base}/v1/rag/query` |
| `RAG_COLLECTION_BASE` | `collection_base` for RAG (default: `taixing_knowledge`) |
| `RAG_K`, `RAG_K_MAX`, `RAG_INCLUDE_RETRIEVAL_HITS` | RAG request fields (defaults: `5`, `40`, `true`) |
| `RAG_HTTP_MAX_ATTEMPTS` | Max POST attempts per RAG call for transient errors (default: `3`; set to `1` to disable retry) |
| `RAG_HTTP_RETRY_BACKOFF_S` | Base delay (seconds) for exponential backoff between RAG retries (default: `0.5`) |
| `USE_MCP_RAG` | `true` (default) to call MCP `rag_query` with stream when `MCP_RAG_BASE_URL` is set; `false` forces HTTP RAG |
| `MCP_RAG_BASE_URL` | MCP origin for streaming `rag_query` (defaults to `RAG_HTTP_BASE_URL`) |
| `USE_MCP_TOOLS` | `true` to route `github_search` through MCP `ask_repo` (default: `false`) |
| `MCP_GITHUB_BASE_URL` | MCP origin for `ask_repo` |
| `TAVILY_API_KEY` | Required for `web_search` tool route |
| `TAVILY_SEARCH_DEPTH` | Tavily search depth (default: `advanced`) |
| `TAVILY_MAX_RESULTS` | Max Tavily results (default: `5`) |
| `ROUTER_PROMPT_VERSION` | Intent router prompt file id under `app/prompts/` (default: `router-v2.00`) |
| `MAX_REQUEST_BODY_MB` | Max request body size for `/v1/orchestrator/answer` (default: `1`) |
| `MAX_HISTORY_MESSAGES` | Max `history` items accepted per answer request (recommended `30-50`, default: `50`) |
| `MAX_QUESTION_CHARS` | Max `question` length in characters (default: `8000`, about 2k tokens) |
| `MAX_CONTEXT_CHARS` | Max total chars across `question` + all `history.content` + effective `conversation_id` (after optional server assignment; default: `120000`) |
| `REQUEST_TIMEOUT_MS` | End-to-end request timeout for orchestrator answer execution (default: `30000`) |
| `STREAM_IDLE_TIMEOUT_MS` | Max idle gap between SSE events before stream timeout (default: `30000`) |
| `MAX_CONCURRENT_DOWNSTREAM_CALLS` | Max concurrent downstream tool/RAG executions (default: `32`; set `0` to disable cap) |
| `TOOLS_TIMEOUT_S` | Timeout for the HTTP RAG client (seconds; default: `60`) |
| `READINESS_TIMEOUT_S` | Timeout for `GET /ready` outbound probes to LLM and RAG (seconds; default: `5`) |
| `READINESS_RAG_QUESTION` | Probe question for RAG on `GET /ready` (default: `.`) |
| `INVOKE_TIMEOUT_S` | Legacy LangGraph invoke timeout (seconds; default: `120`; unused by default pipeline) |
| `LOG_LEVEL` | Logging level (default: `INFO`) |
| `LOG_TIMEZONE` | IANA timezone for log timestamps (default: `America/New_York`) |
| `ENV` | Deployment label included in logs (default `dev`) |
| `LANGCHAIN_PROJECT` | LangSmith project name (optional) |
| `LANGCHAIN_API_KEY` or `LANGSMITH_API_KEY` | LangSmith API key (optional) |
| `LANGCHAIN_ENDPOINT` | LangSmith API endpoint (optional) |
| `LANGSMITH_TRACING` | `true` to enable tracing when configured |

## Run

From the project root:

```bash
uvicorn app.main:app --reload --port 8000
```

### Docker

Build and run locally (port 8000; pass env vars via `--env-file`):

```bash
docker build -t layer-orchestrator-v1 .
docker run -p 8000:8000 --env-file .env layer-orchestrator-v1
```

Run the image published from CI (replace `YOUR_DOCKERHUB_USER` with your Docker Hub username or org):

```bash
docker pull YOUR_DOCKERHUB_USER/layer-orchestrator-v1:latest
docker run -p 8000:8000 --env-file .env YOUR_DOCKERHUB_USER/layer-orchestrator-v1:latest
```

## Health

```bash
curl http://127.0.0.1:8000/health
```

## Metrics (Prometheus)

```bash
curl -s http://127.0.0.1:8000/metrics
```

Exposes HTTP and pipeline metrics including request counts, latency histograms (for p50/p95/p99 via PromQL `histogram_quantile`), route decisions, router/RAG phase durations, and timeout counters.

## Orchestrator (SSE, default)

Omit `stream` or set `"stream": true`. Use `curl -N` and parse SSE events through terminal `{"type":"done",...}`.

```bash
curl -N -s -X POST http://127.0.0.1:8000/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: 123456" \
  -H "X-Request-Id: 12345678" \
  -H "X-Trace-Id: 12345678" \
  -d '{
    "question": "what is taixing visa status?",
    "conversation_id": "conv-demo-1"
  }'
```

## Orchestrator (non-stream JSON)

Set `"stream": false` for one JSON object (same shape as terminal SSE `done`, without `type`).

```bash
curl -s -X POST http://127.0.0.1:8000/v1/orchestrator/answer \
  -H "Content-Type: application/json" \
  -H "X-Session-Id: 123456" \
  -H "X-Request-Id: 12345678" \
  -H "X-Trace-Id: 12345678" \
  -d '{
    "question": "what is taixing visa status?",
    "stream": false,
    "conversation_id": "conv-demo-1"
  }' | jq .
```

## Feedback (SSE)

Submit feedback on an agent response (single SSE `done` or `error` event). The server tries, in order: **`agent_graph_run_id`** (LangSmith root run UUID), **`trace_id`**, then **`request_id`**, as the `run_id` passed to LangSmith `create_feedback`. LangSmith only accepts a real run UUID unless your tracing maps `trace_id` to that run.

**Thumbs up (with trace_id):**

```bash
curl -N -s -X POST http://127.0.0.1:8000/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{"trace_id":"12345678","rating":"thumbs_up"}'
```

**Thumbs down (with type and comment):**

```bash
curl -N -s -X POST http://127.0.0.1:8000/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "trace_id": "12345678",
    "rating": "thumbs_down",
    "feedback_type": "not_factual",
    "comment": "Only returned 3 titles"
  }'
```

`feedback_type` (optional): `not_relevant`, `biased`, `not_factual`, `incomplete_instructions`, `unsafe`, `style_tone`, `other`

## Docker Hub

Pushes to `main` build the [Dockerfile](Dockerfile) and push to Docker Hub via [`.github/workflows/docker-push.yml`](.github/workflows/docker-push.yml). You can also run the workflow manually (**workflow_dispatch**) from the Actions tab.

On **`main` push** (after a successful build), the same workflow updates [huntai-k3s](https://github.com/taixingbi/huntai-k3s) `manifests/orchestrator/overlays/dev/kustomization.yaml` with the **12-char commit SHA** as `images[].newTag`. Argo CD Application `orchestrator-dev` syncs that Git change and rolls out the new image. See [deploy-gitops-argocd.md](https://github.com/taixingbi/huntai-k3s/blob/main/docs/deploy-gitops-argocd.md) in huntai-k3s.

Add these repository secrets under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Docker Hub username or organization |
| `DOCKERHUB_TOKEN` | Docker Hub access token (recommended; not your account password) |
| `HUNTAI_K3S_PAT` | PAT with **contents: write** on `taixingbi/huntai-k3s` (GitOps image pin on `main` push) |

Version flow: `git tag/workflow input -> CI VERSION -> Docker build-arg APP_VERSION -> /health + logs`.

`pyproject.toml` keeps package metadata version for packaging; deployment/runtime version is CI-driven.

Images: `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:latest`, `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:<ci-version>`, and `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:<git-sha>`.

Former Fly.io multi-environment URLs are no longer maintained. Run the container wherever you host services and use the same **Environment (.env)** variables as above. For a public HTTPS host, substitute your base URL for `http://127.0.0.1:8000` in the curl examples.

Logging is emitted as structured JSON to stderr; use Alloy (or your platform collector) to ship logs to Loki.
