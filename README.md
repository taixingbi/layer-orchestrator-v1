# layer-orchestrator-v1

## MCP Orchestrator

FastAPI service: **HTTP chat completions** via `LLM_GATEWAY_BASE_URL` (`POST …/v1/chat/completions`), **HTTP RAG** or MCP RAG, an `answer_question` MCP tool, and **`/orchestrator/stream-answer`** (SSE). Chat calls send `X-Request-Id`, `X-Session-Id`, and `X-Trace-Id` when those ids are available.

## Layout

- **`app/`** — application code (`main.py`, `config.py`, orchestrator, agents, `logging_config.py`, etc.).
- **`main.py`** (repo root) — thin shim that re-exports `app` so you can run `uvicorn main:app` from the project root.

## Documentation

- [Gateway inference](docs/gateway-inference.md) — chat completions URL, model, headers, `curl` example, and tool-calling note.
- [RAG query](docs/rag-query.md) — HTTP RAG `POST /v1/rag/query`, env vars, request body, and `curl` example.

## Setup

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Environment (.env)

Copy or create `.env` at the **project root** (loaded by `app/config.py`). Typical groups: app, LLM, RAG, LangSmith, logging.

| Variable | Description |
|----------|-------------|
| `MCP_NAME` | MCP server / app name (default: `layer-orchestrator-v1`) |
| `APP_VERSION` | App version string (default: `0.1.0`; also used in Loki labels when enabled) |
| `LLM_GATEWAY_BASE_URL` | **Required.** Inference service origin; `/v1` is appended if missing (e.g. `http://host:30180`) |
| `LLM_MODEL` | Chat model id sent in the completion request (default: `Qwen/Qwen2.5-7B-Instruct`) |
| `LLM_API_KEY` | Optional; set if the gateway validates `Authorization` (otherwise a placeholder is sent) |
| `RAG_HTTP_BASE_URL` | RAG service base URL; app calls `POST {base}/v1/rag/query` (takes precedence over MCP RAG) |
| `RAG_COLLECTION_BASE` | `collection_base` for RAG (default: `taixing_knowledge`) |
| `RAG_K`, `RAG_K_MAX`, `RAG_INCLUDE_RETRIEVAL_HITS` | RAG request fields (defaults: `5`, `40`, `true`) |
| `MCP_TOOL_RAG_URL` | RAG MCP HTTP URL (e.g. `https://host/mcp`); used only if `RAG_HTTP_BASE_URL` is unset |
| `TOOLS_TIMEOUT_S` | Timeout for loading MCP tools and for the HTTP RAG client (seconds; default: `60`) |
| `INVOKE_TIMEOUT_S` | LangGraph agent invoke timeout (seconds; default: `120`) |
| `LOG_LEVEL` | Logging level (default: `INFO`) |
| `LOG_TIMEZONE` | IANA timezone for log timestamps (default: `America/New_York`) |
| `ORCHESTRATOR_ENV` / `GATEWAY_ENV` / `ENV` | Deployment label in logs / Loki (first set wins before `ENV`, default `dev`) |
| `GRAFANA_CLOUD_API_KEY` | Optional; with `tb-loki-central-logger` installed, enables shipping logs to Grafana Loki |
| `LOKI_IGNORE_SYSTEM_PROXY` | `1` / `true` if Loki pushes must bypass `HTTP(S)_PROXY` |
| `LANGCHAIN_PROJECT` | LangSmith project name (optional) |
| `LANGCHAIN_API_KEY` or `LANGSMITH_API_KEY` | LangSmith API key (optional) |
| `LANGCHAIN_ENDPOINT` | LangSmith API endpoint (optional) |
| `LANGSMITH_TRACING` | `true` to enable tracing when configured |

## Run

From the project root (either form is valid):

```bash
uvicorn main:app --reload --port 8000
# or
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

## MCP (`answer_question`)

The MCP HTTP transport uses **streamable HTTP** with **SSE** responses by default. **`curl` buffers streamed bodies** unless you pass **`-N`** (`--no-buffer`), so you may see no output until the full response completes or nothing at all if the connection is slow.

The `answer_question` tool accepts **`question`** only. For correlation with logs and the LLM gateway, send **`X-Request-Id`** and **`X-Session-Id`** on the POST.

**Minimal example (SSE; use `-N`):**

```bash
curl -N -s -X POST "http://127.0.0.1:8000/mcp/" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-Request-Id: 12345678" \
  -H "X-Session-Id: 123456" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "answer_question",
      "arguments": {
        "question": "What is your taixing status? Do they require sponsorship?"
      }
    }
  }'
```

**Protocol note:** Many clients send **`initialize`** first, then **`tools/call`**, and reuse the **`mcp-session-id`** header from the initialize response when using stateful sessions. This server runs MCP with **`stateless_http=True`**, so each request is handled in isolation; a single `tools/call` often still works, but for strict clients follow the MCP streamable HTTP sequence. Prefer an **MCP-aware client** (e.g. Cursor, MCP Inspector) for interactive use.

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

Images: `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:latest` and `YOUR_DOCKERHUB_USER/layer-orchestrator-v1:<git-sha>`.

Former Fly.io multi-environment URLs are no longer maintained. Run the container wherever you host services and use the same **Environment (.env)** variables as above. For a public HTTPS host, substitute your base URL for `http://127.0.0.1:8000` in the curl examples.
