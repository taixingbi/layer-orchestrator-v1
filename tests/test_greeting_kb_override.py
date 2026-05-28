"""Greeting + candidate name must not be forced to rag_private_kb."""

import asyncio

from app.core.intent_router import (
    _direct_reply_should_use_rag,
    _is_greeting_smalltalk_utterance,
    maybe_override_internal_for_kb_grounded,
    normalize_post_router,
    run_intent_rewrite_router,
)
from app.core.intent_router import RouterDecision


def test_is_greeting_smalltalk_utterance():
    assert _is_greeting_smalltalk_utterance("Hi Taixing?")
    assert _is_greeting_smalltalk_utterance("Hi Taixing Bi!")
    assert _is_greeting_smalltalk_utterance("Hello?")
    assert not _is_greeting_smalltalk_utterance("What is Taixing's visa?")
    assert not _is_greeting_smalltalk_utterance("Where is Taixing?")


def test_direct_reply_should_use_rag_skips_greeting_with_name():
    assert not _direct_reply_should_use_rag("Hi Taixing?", [])
    assert _direct_reply_should_use_rag("What is Taixing Bi's visa status?", [])
    assert _direct_reply_should_use_rag("Where is Taixing?", [])


def test_kb_override_skips_smalltalk_seed():
    decision = RouterDecision(
        route="greeting",
        rewritten_question="Hi Taixing?",
        static_answer="Hello!",
        reason="[server: smalltalk:greeting_named]",
        source="smalltalk_seed",
    )
    out = maybe_override_internal_for_kb_grounded(decision, "Hi Taixing?", [])
    assert out.route == "greeting"
    assert out.source == "smalltalk_seed"


def test_normalize_post_router_preserves_hi_taixing_greeting():
    decision = RouterDecision(
        route="greeting",
        rewritten_question="Hi Taixing?",
        static_answer="Hello!",
        reason="[server: smalltalk:greeting_named]",
        source="smalltalk_seed",
    )
    out = normalize_post_router(decision, latest_question="Hi Taixing?", history=[])
    assert out.route == "greeting"


def test_run_intent_router_hi_taixing_is_greeting():
    decision = asyncio.run(run_intent_rewrite_router("Hi Taixing?", []))
    assert decision.route == "greeting"
    out = normalize_post_router(decision, latest_question="Hi Taixing?", history=[])
    assert out.route == "greeting"
