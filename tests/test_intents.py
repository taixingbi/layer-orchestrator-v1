"""Internal intent matching."""

from app.intents.identity import IDENTITY_ANSWER, match_identity
from app.intents.registry import match_internal_intent


def test_match_identity():
    assert match_identity("What is your name?")
    hit = match_internal_intent("What is your name?")
    assert hit is not None
    detail, answer = hit
    assert detail.name == "identity"
    assert answer == IDENTITY_ANSWER


def test_match_greeting():
    hit = match_internal_intent("Hi!")
    assert hit is not None
    assert hit[0].name == "greeting"


def test_match_capabilities():
    hit = match_internal_intent("What can you do?")
    assert hit is not None
    assert hit[0].name == "capabilities"
