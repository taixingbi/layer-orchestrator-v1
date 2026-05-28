# Router routes and enums

The orchestrator router picks a **canonical `route`** per user turn. That string is the single source of truth for the LLM router, gold tests, and DPO. Nested `route_detail` is derived only for SSE and client envelopes.

**Code:** [`app/schemas/route.py`](../app/schemas/route.py) · **Decision model:** [`app/core/intent_router.py`](../app/core/intent_router.py) (`RouterDecision`) · **Flow:** [intent-router.md](intent-router.md) · **Gold CSVs:** [gold-test/readme.md](../gold-test/readme.md)

## `CanonicalRoute` (10 values)

Defined as `CanonicalRoute` in `app/schemas/route.py`. Used on `RouterDecision.route` and gold `expected_route`.

### Tools (`TOOL_ROUTES`)

| Route | Downstream |
|-------|------------|
| `rag_private_kb` | Private KB / RAG (HTTP or MCP `rag_query`) |
| `github_search` | Org GitHub repo search (MCP) |
| `web_search` | Tavily public web search |

### Internal intents (`INTERNAL_ROUTES`)

| Route | Typical use |
|-------|-------------|
| `greeting` | Hi / how are you |
| `identity` | Who are you / your name |
| `help` | General help or public-knowledge answer (`static_answer`) |
| `capabilities` | What can you do |
| `clarify` | Ambiguous ask; prompt in `static_answer` |
| `reject` | Unsafe / blocked (injection guard or model) |

Union set: `CANONICAL_ROUTES = TOOL_ROUTES | INTERNAL_ROUTES`.

## `RouterDecision` (router JSON)

| Field | Type | Notes |
|-------|------|--------|
| `route` | `CanonicalRoute` | Required |
| `rewritten_question` | string | Standalone query; third person for KB asks |
| `confidence` | float 0–1 | From LLM; used for low-confidence post-rules |
| `reason` | string | Model or server annotation |
| `source` | string | How the route was chosen (see below) |
| `static_answer` | string \| null | Internal routes only (replaces legacy `direct_answer`) |
| `repo` | string \| null | Optional; `github_search` |

Example:

```json
{
  "route": "rag_private_kb",
  "rewritten_question": "What is Taixing Bi's current visa status?",
  "confidence": 0.94,
  "reason": "Question asks about user-specific private profile information",
  "source": "llm_router",
  "static_answer": null,
  "repo": null
}
```

### `source` / `route_source` values

| `source` | Meaning |
|----------|---------|
| `guard` | Injection guard (pre-LLM) |
| `smalltalk_seed` | Exact match on `smalltalk_examples.json` |
| `llm_router` | Versioned router prompt LLM |
| `post_rule` | Server override (GitHub keyword, KB-grounded, low confidence, etc.) |
| `fallback` | Empty input, parse error, or invoke error |

Pre-LLM deterministic intents from [`app/core/router.py`](../app/core/router.py) (`resolve_route`) use envelope `route_source` from [`answer_envelope.py`](../app/schemas/answer_envelope.py) (`deterministic_rule`).

## Envelope-only types (not router enum)

Clients still receive nested `route_detail`:

| Type | `type` field | `name` field uses |
|------|----------------|-------------------|
| `ToolRoute` | `"tool"` | `ToolName` — same three tool ids as canonical tool routes |
| `InternalIntentRoute` | `"internal_intent"` | `InternalIntentName` — same six internal ids |

Built via `canonical_to_route_detail(route, …)` at the pipeline boundary.

## Legacy routes (compat only)

`LegacyRoute`: `rag` | `direct_reply` | `clarify` | `reject` | `tool`

Parsed JSON and old gold labels are normalized into `CanonicalRoute`:

| Legacy | Canonical |
|--------|-----------|
| `rag` | `rag_private_kb` |
| `tool` (+ optional `route_detail.name`) | tool name or `github_search` |
| `direct_reply` | `help` (or internal name from `route_detail`) |
| `clarify` | `clarify` |
| `reject` | `reject` |

Gold eval may still send legacy `expected_route`; [`normalize_gold_expected_route`](../app/schemas/route.py) maps them before compare.

## Gold test files

Suite CSVs under `gold-test/data/` use **`router_<route>.csv`** in subfolders:

| Path | Primary focus |
|------|----------------|
| `data/internal-intent/router_greeting.csv` | `greeting` |
| `data/internal-intent/router_identity.csv` | `identity` |
| `data/internal-intent/router_capabilities.csv` | `capabilities` |
| `data/internal-intent/router_help.csv` | `help` |
| `data/internal-intent/router_reject.csv` | `reject` |
| `data/tools/router_rag_private_kb.csv` | `rag_private_kb` |
| `data/tools/router_github.csv` | `github_search` |
| `data/tools/router_web_search.csv` | `web_search` |

## Router prompt

Default: [`app/prompts/router-v2.00.txt`](../app/prompts/router-v2.00.txt) (`ROUTER_PROMPT_VERSION`). The LLM must return canonical `route` and must not emit legacy `rag` / `direct_reply` / `route_detail` in new prompts.

Older test prompts (e.g. `router-test-v1.04`) still use legacy route names; the server normalizes them on `RouterDecision` parse.

## See also

- [intent-router.md](intent-router.md) — execution order, guards, post-rules
- [smalltalk-seed.md](smalltalk-seed.md) — FAQ / greeting seed JSON
- [gold-test/readme.md](../gold-test/readme.md) — batch eval harness
- [dpo-router/README.md](../dpo-router/README.md) — preference data from gold
