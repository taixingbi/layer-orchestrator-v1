# `conversation_id`

**What it is:** A thread id for your chat. Send it in the JSON body on `POST /v1/orchestrator/answer` and `POST /v1/orchestrator/eval/router`.

**If you skip it or send only blanks:** The server assigns `conv_` + 32 hex chars and sets **`is_new_conversation`: true** in API responses. If you send a non-blank id, **`is_new_conversation`** is **false**.

**Where you see it:** JSON response (or first SSE `correlation` event; legacy `type: "request_id"`). **Structured logs** include top-level **`conversation_id`** (effective id for `/v1/orchestrator/answer` and `/v1/orchestrator/eval/router` on `http_request_complete`; otherwise from request context when bound).

## Gateways (outbound design)

This app calls **two HTTP gateways**. Both receive the same **conversation** headers whenever an effective id exists:

| Gateway | Call | Headers (thread) |
|---------|------|-------------------|
| **Inference** | `POST {LLM_GATEWAY_BASE_URL}/…/v1/chat/completions` | `X-Conversation-Id`, `X-Is-New-Conversation` (with `X-Request-Id`, `X-Session-Id`, `X-Trace-Id` when provided) |
| **RAG** | `POST {RAG_HTTP_BASE_URL}/v1/rag/query` | Same thread headers; **plus** `conversation_id` in the JSON body |

So: **one rule for all gateways** — thread id and new-thread flag ride on **`X-Conversation-Id`** / **`X-Is-New-Conversation`**; RAG additionally mirrors **`conversation_id`** in the payload for services that prefer body fields.

**More detail:** [correlation-ids.md](correlation-ids.md) · [schema-request-response.md](schema/schema-request-response.md) · [gateway-inference.md](gateway-inference.md) · [rag-query.md](rag-query.md)
