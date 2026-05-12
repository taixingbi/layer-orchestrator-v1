# Small-talk seed (FAQ / greetings)

Greetings and lightweight **assistant / meta** questions are answered from **structured seed JSON**, not from vector RAG and **without** a router LLM call when the match conditions are met.

## File and schema

| Item | Location |
|------|----------|
| Seed catalog | [`app/prompts/smalltalk_examples.json`](../app/prompts/smalltalk_examples.json) |
| Loader and match | [`app/intent_rewrite_router.py`](../app/intent_rewrite_router.py) (`_load_smalltalk_seed`, `_match_smalltalk_seed`, `run_intent_rewrite_router`) |

Each array element is an object:

| Field | Type | Meaning |
|-------|------|---------|
| `intent` | string | Stable id for logging and `router.smalltalk_intent` on eval (e.g. `greeting_hi`, `bot_name`). |
| `user_examples` | string[] | Phrases that trigger this entry (**exact** match after normalization; see below). |
| `answer` | string | `direct_reply` body. May contain `__CANDIDATE_NAME__`; it is replaced with the configured candidate name at match time (same substitution as router `.txt` prompts). |

Order matters: the **first** entry whose `user_examples` matches the latest question wins.

## Normalization and match

1. Trim the latest user question, lowercase it, and collapse runs of whitespace to a single space (`_normalize_smalltalk_key`).
2. Compare that string to each `user_examples` string normalized the same way.
3. Match is **equality only** (no fuzzy search, no embeddings).

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

- `prompt_source`: `smalltalk_seed`
- `smalltalk_intent`: matched `intent`
- `prompt_file` / `prompt_requested_fallback`: `null`

The router **LLM is not invoked** on this path. Post-router helpers such as `_ensure_rewritten_question_third_person` and `maybe_override_rag_for_general_question` apply only to the **LLM** decision path, not to the small-talk short-circuit.

## Packaging

`app/prompts/*.json` is listed in [`pyproject.toml`](../pyproject.toml) under `[tool.setuptools.package-data]` so wheels and installs include the seed file.

## API and gold tests

- **`POST /orchestrator/eval/router`** returns `router.smalltalk_intent` when the seed path was used. See [schema-request-response.md](schema-request-response.md) (`POST /orchestrator/eval/router`).
- Gold inputs for seed-FAQ / small-talk rows: [`gold-test/data/router-gold-seed-faq.csv`](../gold-test/data/router-gold-seed-faq.csv). Runner and columns: [`gold-test/README.md`](../gold-test/README.md).

## Router prompts

Router text files (e.g. `router-v1.02.txt`) mention that the server may short-circuit **empty-history** questions that match `smalltalk_examples.json` before the model runs.

## Follow-ups (not implemented)

- Paraphrase / fuzzy match (embeddings or classifiers).
- Small-talk when **history is non-empty** (needs explicit policy to avoid hijacking candidate threads).
