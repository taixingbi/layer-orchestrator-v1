"""MCP server and orchestrator_stream_answer tool."""

from mcp.server import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .config import settings
from .orchestrator import answer_query_sync, format_error

# streamable_http_path="/" so mounted at /mcp matches (path becomes /)
mcp = FastMCP(
    settings.mcp_name,
    stateless_http=True,
    streamable_http_path="/",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)


@mcp.tool(name="answer_question")
async def tool_mcp_answer(question: str) -> str:
    """Answer a question using RAG tools. Returns the full answer text."""
    try:
        return await answer_query_sync(
            question,
            tools_timeout_s=settings.tools_timeout_s,
            invoke_timeout_s=settings.invoke_timeout_s,
        )
    except Exception as e:
        return format_error(e)


mcp_app = mcp.streamable_http_app()
