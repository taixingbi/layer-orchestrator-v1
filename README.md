# layer-orchestrator-v1

## FastAPI Orchestrator

FastAPI service: **HTTP chat completions** via `LLM_GATEWAY_BASE_URL` (`POST …/v1/chat/completions`), **HTTP RAG**, and **`/orchestrator/stream-answer`** (SSE). Chat calls send `X-Request-Id`, `X-Session-Id`, and `X-Trace-Id` when those ids are available.

## Layout

- **`app/`** — application code (`main.py`, `config.py`, orchestrator, agents, `logging_config.py`, etc.).

## Documentation

- [Gateway inference](docs/gateway-inference.md) — chat completions URL, model, headers, `curl` example, and tool-calling note.
- [RAG query](docs/rag-query.md) — HTTP RAG `POST /v1/rag/query`, env vars, request body, and `curl` example.
- [Design](docs/design.md) — architecture, request flows, reliability loop, and trade-offs.

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
| `TOOLS_TIMEOUT_S` | Timeout for the HTTP RAG client (seconds; default: `60`) |
| `INVOKE_TIMEOUT_S` | LangGraph agent invoke timeout (seconds; default: `120`) |
| `LOG_LEVEL` | Logging level (default: `INFO`) |
| `LOG_TIMEZONE` | IANA timezone for log timestamps (default: `America/New_York`) |
| `ENV` | Deployment label in logs / Loki (default `dev`) |
| `GRAFANA_CLOUD_API_KEY` | Optional; with `tb-loki-central-logger` installed, enables shipping logs to Grafana Loki |
| `LOKI_IGNORE_SYSTEM_PROXY` | `1` / `true` if Loki pushes must bypass `HTTP(S)_PROXY` |
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

## Orchestrator SSE

```bash
curl -N -s -X POST http://127.0.0.1:8000/orchestrator/stream-answer \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "123456",
    "request_id": "12345678",
    "question": "what is taixing visa status?"
  }'
```

## Feedback

Submit feedback on an agent response. Use `agent_graph_run_id` from the **`answer`** SSE event of **`/orchestrator/stream-answer`** (or `request_id` from the first event) to attach feedback to the agent_graph run in LangSmith.

**Thumbs up (with agent_graph_run_id):**

```bash
curl -s -X POST http://127.0.0.1:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{"agent_graph_run_id":"c111d890-55c2-40ec-ba23-84a18ffa91f1","rating":"thumbs_up"}'
```

**Thumbs down (with type and comment):**

```bash
curl -s -X POST http://127.0.0.1:8000/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "agent_graph_run_id": "019c5f54-0667-7531-9b48-62a65710fd2c",
    "rating": "thumbs_down",
    "feedback_type": "not_factual",
    "comment": "Only returned 3 titles"
  }'
```

`feedback_type` (optional): `not_relevant`, `biased`, `not_factual`, `incomplete_instructions`, `unsafe`, `style_tone`, `other`

## Docker Hub

Pushes to `main` build the [Dockerfile](Dockerfile) and push to Docker Hub via [`.github/workflows/docker-push.yml`](.github/workflows/docker-push.yml). You can also run the workflow manually (**workflow_dispatch**) from the Actions tab.

Add these repository secrets under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|--------|-------------|
| `DOCKERHUB_USERNAME` | Docker Hub username or organization |
| `DOCKERHUB_TOKEN` | Docker Hub access token (recommended; not your account password) |

Version flow: `git tag/workflow input -> CI VERSION -> Docker build-arg APP_VERSION -> /health + logs`.

`pyproject.toml` keeps package metadata version for packaging; deployment/runtime version is CI-driven.

Images: `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:latest`, `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:<ci-version>`, and `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:<git-sha>`.

Former Fly.io multi-environment URLs are no longer maintained. Run the container wherever you host services and use the same **Environment (.env)** variables as above. For a public HTTPS host, substitute your base URL for `http://127.0.0.1:8000` in the curl examples.
