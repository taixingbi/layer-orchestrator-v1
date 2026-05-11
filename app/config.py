"""Application settings loaded from environment."""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from . import __version__

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
load_dotenv()

# Cached LangChain chat HTTP clients, keyed by (model, base_url, temperature)
_llm_instances: Dict[tuple, Any] = {}


class Settings:
    """Settings from env (and .env)."""

    # App
    app_name: str = os.getenv("APP_NAME", os.getenv("MCP_NAME", "layer-orchestrator-v1"))
    app_version: str = os.getenv("APP_VERSION") or __version__

    # LangChain / LangSmith
    langchain_project: Optional[str] = os.getenv("LANGCHAIN_PROJECT")
    langchain_api_key: Optional[str] = os.getenv("LANGCHAIN_API_KEY")
    langsmith_api_key: Optional[str] = os.getenv("LANGSMITH_API_KEY")
    langchain_endpoint: Optional[str] = os.getenv("LANGCHAIN_ENDPOINT")
    langsmith_tracing: bool = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"

    # RAG via HTTP: base URL only; code POSTs to /v1/rag/query
    rag_http_base_url: Optional[str] = os.getenv("RAG_HTTP_BASE_URL")
    rag_collection_base: str = os.getenv("RAG_COLLECTION_BASE", "taixing_knowledge")
    rag_k: int = int(os.getenv("RAG_K", "5"))
    rag_k_max: int = int(os.getenv("RAG_K_MAX", "40"))
    rag_include_retrieval_hits: bool = (
        os.getenv("RAG_INCLUDE_RETRIEVAL_HITS", "true").lower() == "true"
    )
    # Transient RAG HTTP failures: retry with exponential backoff (see app/rag_http_tool.py).
    rag_http_max_attempts: int = max(1, int(os.getenv("RAG_HTTP_MAX_ATTEMPTS", "3")))
    rag_http_retry_backoff_s: float = float(os.getenv("RAG_HTTP_RETRY_BACKOFF_S", "0.5"))
    # Workflow safety limits (application-level safeguards).
    max_request_body_mb: float = float(os.getenv("MAX_REQUEST_BODY_MB", "1"))
    max_history_messages: int = max(1, int(os.getenv("MAX_HISTORY_MESSAGES", "50")))
    max_question_chars: int = max(1, int(os.getenv("MAX_QUESTION_CHARS", "8000")))
    max_context_chars: int = max(1, int(os.getenv("MAX_CONTEXT_CHARS", "120000")))
    request_timeout_ms: int = max(1, int(os.getenv("REQUEST_TIMEOUT_MS", "30000")))
    stream_idle_timeout_ms: int = max(1, int(os.getenv("STREAM_IDLE_TIMEOUT_MS", "30000")))
    max_concurrent_downstream_calls: int = int(os.getenv("MAX_CONCURRENT_DOWNSTREAM_CALLS", "32"))

    # LLM: HTTP chat completions at {LLM_GATEWAY_BASE_URL}/v1/chat/completions
    llm_gateway_base_url: Optional[str] = os.getenv("LLM_GATEWAY_BASE_URL")
    llm_model: str = os.getenv("LLM_MODEL") or "Qwen/Qwen2.5-7B-Instruct"

    # Default timeouts (seconds)
    tools_timeout_s: float = float(os.getenv("TOOLS_TIMEOUT_S", "60"))
    invoke_timeout_s: float = float(os.getenv("INVOKE_TIMEOUT_S", "120"))
    readiness_timeout_s: float = float(os.getenv("READINESS_TIMEOUT_S", "5"))


settings = Settings()


def normalized_llm_base_url() -> Optional[str]:
    """Base URL for chat completions, e.g. http://host:30180/v1."""
    u = (settings.llm_gateway_base_url or "").strip().rstrip("/")
    if not u:
        return None
    if not u.endswith("/v1"):
        u = f"{u}/v1"
    return u


def gateway_extra_headers(
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, str]:
    """Optional tracing headers on chat completion requests."""
    h: Dict[str, str] = {}
    rid = (request_id or "").strip()
    sid = (session_id or "").strip()
    tid = (trace_id or rid or "").strip()
    if rid:
        h["X-Request-Id"] = rid
    if sid:
        h["X-Session-Id"] = sid
    if tid:
        h["X-Trace-Id"] = tid
    return h


def gateway_llm_invoke_kwargs(
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Extra kwargs for chat model ainvoke when using the configured gateway."""
    if not normalized_llm_base_url():
        return {}
    hdrs = gateway_extra_headers(request_id, session_id, trace_id)
    return {"extra_headers": hdrs} if hdrs else {}


def get_llm(temperature: float = 0):
    """Return a cached LangChain chat client for POST /v1/chat/completions on the gateway."""
    base = normalized_llm_base_url()
    if not base:
        raise ValueError(
            "LLM_GATEWAY_BASE_URL is required (e.g. http://192.168.86.179:30180)"
        )
    # Transport: langchain-openai package (HTTP JSON to /v1/chat/completions).
    from langchain_openai import ChatOpenAI as ChatCompletionsClient

    key = (settings.llm_model, base, temperature)
    if key not in _llm_instances:
        kw: Dict[str, Any] = {
            "model": settings.llm_model,
            "temperature": temperature,
            "base_url": base,
            "api_key": os.getenv("LLM_API_KEY") or "not-needed",
        }
        _llm_instances[key] = ChatCompletionsClient(**kw)
    return _llm_instances[key]


def has_langsmith_credentials() -> bool:
    """True if we have an API key to call LangSmith (LANGCHAIN_API_KEY or LANGSMITH_API_KEY)."""
    return bool(settings.langchain_api_key or settings.langsmith_api_key)


def get_langsmith_tags(
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> List[str]:
    """Build tags for LangSmith traces (key:value format). Optionally include request_id and session_id."""
    tags = [
        f"app_name:{settings.app_name}",
        f"agent_model:{settings.llm_model}",
        f"agent_has_rag:{bool(settings.rag_http_base_url)}",
    ]
    if settings.langchain_project:
        tags.append(f"langchain_project:{settings.langchain_project}")
    if settings.langsmith_tracing:
        tags.append("langsmith_tracing:true")
    if request_id:
        tags.append(f"request_id:{request_id}")
    if session_id:
        tags.append(f"session_id:{session_id}")
    return tags

