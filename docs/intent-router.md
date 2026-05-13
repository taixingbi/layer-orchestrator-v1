# Intent router (rewrite + route)

This document describes how **`run_intent_rewrite_router`** in [`app/intent_rewrite_router.py`](../app/intent_rewrite_router.py) chooses **`route`** (`rag` | `direct_reply` | `clarify` | `reject`), fills **`direct_answer`** when applicable, and produces **`rewritten_question`** for downstream RAG or clients.

For HTTP field names and eval payloads, see [schema-request-response.md](schema-request-response.md). For empty-history FAQ/greetings without an LLM, see [smalltalk-seed.md](smalltalk-seed.md).

## Goals

- **Single decision** per turn: classify the latest user message and optionally rewrite it for retrieval.
- **Stable, cheap path** for repeated assistant/meta questions when there is **no conversation history** (JSON seed + small regex layer).
- **One LLM call** when the small-talk path does not apply: system prompt from a versioned **`.txt`** file + user message with optional history.
- **Server-side rails** after the LLM: general immigration/process wording without naming the candidate can be forced to **`direct_reply`**; RAG-bound queries get **third-person** rewrites about the configured candidate.
- **Prompt-injection guard:** deterministic patterns on the **latest message only** return **`reject`** or a safe **`direct_reply`** before the router LLM (not a substitute for authz on tools and data paths).

## Output contract (`RouterDecision`)

| Field | Role |
|-------|------|
| `rewritten_question` | Standalone query string; for **`rag`**, expected to be search-friendly and third person about the candidate where applicable. |
| `route` | `rag` → LangGraph + HTTP RAG; `direct_reply` / `clarify` / `reject` → final answer path without the RAG graph (see [architecture.md](architecture.md)). |
| `can_answer_directly` | Whether the model believes a direct string answer is appropriate (aligned with `direct_reply` / `clarify` usage). |
| `direct_answer` | User-visible answer body when the route supplies one; may be `null` on `rag`. |
| `reason` | Short model or server annotation (eval and logs). |

## Execution order

### 1. Empty question

If the latest question is empty after trim, the router returns a conservative fallback (**`rag`**) with a third-person rewrite (see `fallback_router_decision`).

### 2. Prompt-injection guard (**hard logic**, latest message only)

**`_prompt_injection_hard_block`** runs immediately after the empty-question check and **before** small-talk and **before** any router LLM call. It inspects a normalized form of the latest user text (same trim / lowercase / whitespace collapse as small-talk normalization).

Typical outcomes:

- **`reject`** — Known exfiltration or instruction-override phrases (for example ignoring prior instructions or rules, repeating developer/system messages, asking for secrets, fake admin lines (including lone “you are now admin?”), fake admin + password, email-to-exfil company files, “show your reasoning” chain leaks, admin override, reveal system prompt, show hidden data). **`direct_answer`** is `null`; the orchestrator uses a short default refusal string for the user.

On hit, **`runtime_meta.prompt_source`** is **`injection_guard`**, `prompt_file` is `null`, and **`reason`** starts with **`[server: injection_guard:…]`**. This layer is **not** a complete security boundary: tool access and data still must be enforced with real authorization (for example “if role != admin, do not attach privileged tools”), as the LLM cannot be trusted to enforce policy alone.

### 3. Small-talk short-circuit (**history must be empty**)

If `normalize_history_turns(history)` yields **no** turns:

1. **`_match_smalltalk_any`** runs **before** any LLM call.
2. **Layer A — exact:** normalized equality against each `user_examples` string in [`app/prompts/smalltalk_examples.json`](../app/prompts/smalltalk_examples.json).
3. **Layer B — patterns:** short utterance (length cap), trailing punctuation stripped, **`fullmatch`** on ordered regexes in code; each rule maps to an **`intent`**; **`answer`** is read from the JSON row with that intent.

On hit:

- **`route`**: `direct_reply`
- **`direct_answer`**: rendered answer (including `__CANDIDATE_NAME__` substitution)
- **`rewritten_question`**: original user text (unchanged)
- **`reason`**: `[server: smalltalk:<intent>]`
- **No** `maybe_override_rag_for_general_question` or `_ensure_rewritten_question_third_person` on this path.

Callers that pass `runtime_meta` (for example **`POST /orchestrator/eval/router`**) receive `prompt_source` of `smalltalk_seed` or `smalltalk_pattern` and `smalltalk_intent`. Details: [smalltalk-seed.md](smalltalk-seed.md).

### 4. LLM router (default path)

1. **System prompt** from:
   - request **`router_system_prompt`** override (if non-empty), else
   - **`app/prompts/{router_prompt_version}.txt`**, with `__CANDIDATE_NAME__` replaced like other stored prompts.
2. **User message**: capped **history** block + **latest question** (see `format_history_for_prompt` / `REWRITE_HISTORY_MAX_LINES`).
3. **Model** returns text; the server extracts a **JSON object** (markdown fences stripped), then validates **`RouterDecision`**.

### 5. Post-processing (**LLM path only**)

Applied in order after a successful parse:

1. **`maybe_override_rag_for_general_question`** — If the model chose **`rag`** but the latest line matches a **general immigration / work-authorization** keyword regex and does **not** name the candidate, the server switches to **`direct_reply`** with a fixed high-level disclaimer answer. Rationale: avoid treating broad policy questions as document-only retrieval when no candidate-specific grounding was asked for.

2. **`_ensure_rewritten_question_third_person`** — For **`rag`**, **`rewritten_question`** is passed through **`rewrite_to_third_person`**. On non-`rag` routes, if the model echoed the raw question verbatim and it still contains second-person pronouns, it may be rewritten (with an exception when the immigration override applies).

### 6. Parse or invoke failure

Same as parse failure: **`fallback_router_decision`** (`rag`) plus the two post-processing steps above.

### 7. `normalize_post_router` (callers after return)

[`normalize_post_router`](../app/intent_rewrite_router.py) runs in **`app/orchestrator.py`** and eval in **`app/main.py`**: if **`route`** is **`direct_reply`** but **`direct_answer`** is empty, the decision is adjusted to **`clarify`** with a short default message so the client never gets a blank direct reply.

## Prompt assets (split responsibilities)

| Asset | Format | Role |
|-------|--------|------|
| `app/prompts/router-*.txt` | Plain text | LLM **routing policy** and examples; version id from `ROUTER_PROMPT_VERSION` / request. |
| `app/prompts/smalltalk_examples.json` | JSON array | Catalog of intents, `user_examples`, and `answers` for the **empty-history** server path. |
| `_SMALLTALK_PATTERN_RULES` in code | Regex → intent | Second layer for short paraphrases; answers still loaded from JSON by `intent`. |
| `_prompt_injection_hard_block` in code | Regex / fullmatch | Latest-only jailbreak / exfil phrases → **`reject`** or one safe **`direct_reply`**. |

Router prompts are **not** JSON: the loader reads **`{id}.txt`** as the system string sent to the chat model.

## Observability

- Successful LLM completion logs **`intent_router_completed`** with latency and previews.
- Small-talk hits log **`intent_router_smalltalk_seed`** or **`intent_router_smalltalk_pattern`**.
- Injection guard hits log **`intent_router_injection_guard`**.
- Eval responses expose `router.prompt_source`, `router.prompt_file`, `router.smalltalk_intent`, etc. See [schema-request-response.md](schema-request-response.md).

## Related code

- [`app/intent_rewrite_router.py`](../app/intent_rewrite_router.py) — `run_intent_rewrite_router`, `RouterDecision`, `normalize_post_router`, `_prompt_injection_hard_block`, small-talk helpers, immigration override, third-person enforcement.
- [`app/agent_rewrite.py`](../app/agent_rewrite.py) — `normalize_history_turns`, `format_history_for_prompt`, `rewrite_to_third_person`.
- [`app/config.py`](../app/config.py) — `default_router_prompt_version` (`ROUTER_PROMPT_VERSION`).
