"""Rewrite and history helpers (re-export from agent_rewrite)."""

from ..agent_rewrite import (
    ANSWER_HISTORY_MAX_LINES,
    CANDIDATE_NAME,
    HISTORY_CAP,
    REWRITE_HISTORY_MAX_LINES,
    format_history_for_prompt,
    history_snippet_for_answer,
    normalize_history_turns,
    rewrite_to_third_person,
)

__all__ = [
    "ANSWER_HISTORY_MAX_LINES",
    "CANDIDATE_NAME",
    "HISTORY_CAP",
    "REWRITE_HISTORY_MAX_LINES",
    "format_history_for_prompt",
    "history_snippet_for_answer",
    "normalize_history_turns",
    "rewrite_to_third_person",
]
