# Correlation IDs (`request_id`, `session_id`, `trace_id`, `conversation_id`)

## Ingress (`POST /v1/orchestrator/answer`, `/eval/router`)

| ID | Where | If omitted |
|----|--------|------------|
| `request_id` | Header `X-Request-Id` | Server generates UUID |
| `session_id` | Header `X-Session-Id` | Server generates `ses_<hex>` (one id per HTTP request) |
| `trace_id` | Header `X-Trace-Id` | Defaults to `request_id`; logs include `trace_id_source`: `header` or `request_id` |
| `conversation_id` | JSON body only | Server assigns `conv_<hex>`, `is_new_conversation: true` |

**Rejected in JSON body (400):** `request_id`, `session_id`, `trace_id`, user relay fields.

## Multi-turn clients

- Send the **same** `X-Session-Id` on every turn in a chat session.
- Send the **same** `conversation_id` in the body (or omit only on the first turn and reuse the id returned by the server).
- **layer-gateway-api-v1** mints `sess_<hex>` when `X-Session-Id` is missing and forwards it to the orchestrator.
- **layer-rag-query-v1** mints a new `session_id` per request when the header is missing; the orchestrator now always sends a session id on outbound RAG/MCP calls.

## SSE (orchestrator stream)

First event: `type: "correlation"` with all ids (legacy alias `type: "request_id"`). See [schema-request-response.md](schema/schema-request-response.md).

## Outbound

| Target | Headers | Body |
|--------|---------|------|
| Inference gateway | `X-Request-Id`, `X-Session-Id`, `X-Trace-Id`, `X-Conversation-Id`, `X-Is-New-Conversation` | — |
| RAG HTTP | same | `conversation_id` when set |
| MCP (RAG, GitHub) | same thread headers on HTTP | tool `arguments` may include `conversation_id` |

See also [conversation-id.md](conversation-id.md), [rag-query.md](rag-query.md), [gateway-inference.md](gateway-inference.md).
