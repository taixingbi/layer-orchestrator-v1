# Small-talk seed (FAQ / greetings)

Greetings and lightweight **assistant / meta** questions are answered from **structured seed JSON**, not from vector RAG and **without** a router LLM call when the match conditions are met.

## File and schema

| Item | Location |
|------|----------|
| Seed catalog | [`app/prompts/smalltalk_examples.json`](../app/prompts/smalltalk_examples.json) |
| Loader and match | [`app/intent_rewrite_router.py`](../app/intent_rewrite_router.py) (`_load_smalltalk_seed`, `_match_smalltalk_seed`, `_match_smalltalk_patterns`, `_match_smalltalk_any`, `run_intent_rewrite_router`) |

Each array element is an object:

| Field | Type | Meaning |
|-------|------|---------|
| `intent` | string | Stable id for logging and `router.smalltalk_intent` on eval (e.g. `greeting_hi`, `bot_name`). |
| `user_examples` | string[] | Phrases that trigger this entry (**exact** match after normalization; see below). |
| `answer` | string | `direct_reply` body. May contain `__CANDIDATE_NAME__`; it is replaced with the configured candidate name at match time (same substitution as router `.txt` prompts). |

Order matters: the **first** entry whose `user_examples` matches the latest question wins.

## Two layers (empty history only)

1. **Exact match (layer 1)** — Same normalization as below; string must equal a `user_examples` entry. `prompt_source`: **`smalltalk_seed`**.
2. **Regex patterns (layer 2)** — If layer 1 misses: normalize, strip trailing `!?.;:,`, enforce a **short** length cap, then **`fullmatch`** against ordered rules in code. Each rule maps to an **`intent`**; the **`answer`** is loaded from the **first JSON row** with that `intent` (single source of truth for copy). `prompt_source`: **`smalltalk_pattern`**. No embeddings; patterns are conservative (whole short utterance).

## Normalization (layer 1)

1. Trim the latest user question, lowercase it, and collapse runs of whitespace to a single space (`_normalize_smalltalk_key`).
2. Compare that string to each `user_examples` string normalized the same way.
3. Match is **equality only** between user text and catalog examples.

## When it runs

- **After** `normalize_history_turns(history)` in `run_intent_rewrite_router`.
- **Only if history is empty** (no prior user/assistant turns). If there is history, the flow goes to the **LLM intent router** as usual.

This avoids treating mid-conversation lines like “What is your name?” as global small-talk unless you extend the product rules later.

## Response shape

On a hit:

- `route`: `direct_reply`
- `direct_answer`: rendered seed `answer`
- `rewritten_question`: original user text
- `reason`: `[server: smalltalk:<intent>]`

`runtime_meta` (when passed in, e.g. from eval):

- `prompt_source`: `smalltalk_seed` or `smalltalk_pattern`
- `smalltalk_intent`: matched `intent`
- `prompt_file` / `prompt_requested_fallback`: `null`

The router **LLM is not invoked** on this path. Post-router helpers such as `_ensure_rewritten_question_third_person` and `maybe_override_rag_for_general_question` apply only to the **LLM** decision path, not to the small-talk short-circuit.

## Packaging

`app/prompts/*.json` is listed in [`pyproject.toml`](../pyproject.toml) under `[tool.setuptools.package-data]` so wheels and installs include the seed file.

## API and gold tests

- **`POST /orchestrator/eval/router`** returns `router.smalltalk_intent` when either small-talk path was used (`router.prompt_source` is `smalltalk_seed` or `smalltalk_pattern`). See [schema-request-response.md](schema-request-response.md) (`POST /orchestrator/eval/router`).
- Gold inputs for seed-FAQ / small-talk rows: [`gold-test/data/router-gold-seed-faq.csv`](../gold-test/data/router-gold-seed-faq.csv). Runner and columns: [`gold-test/README.md`](../gold-test/README.md).

## Router prompts

Router text files (e.g. `router-v1.02.txt`) mention that the server may short-circuit **empty-history** questions that match the seed catalog or server-side patterns before the model runs.

## Follow-ups (not implemented)

- Embedding or classifier–based paraphrase beyond the fixed regex list.
- Small-talk when **history is non-empty** (needs explicit policy to avoid hijacking candidate threads).
