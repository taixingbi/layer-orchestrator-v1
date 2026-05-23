"""Submit feedback to LangSmith."""

import logging
from typing import Literal, Optional

from langsmith import Client
from pydantic import BaseModel, Field

from ..config import has_langsmith_credentials

LANGSMITH_FEEDBACK_KEY = "user_rating"

FEEDBACK_TYPES = frozenset([
    "not_relevant",
    "biased",
    "not_factual",
    "incomplete_instructions",
    "unsafe",
    "style_tone",
    "other",
])


class FeedbackBody(BaseModel):
    """Feedback on an agent response."""

    request_id: Optional[str] = Field(None, description="request_id from headers / first SSE event (optional)")
    trace_id: Optional[str] = Field(None, description="X-Trace-Id / JSON trace_id; preferred id for feedback when LangSmith run matches trace")
    agent_graph_run_id: Optional[str] = Field(
        None,
        description="LangSmith root run UUID if known; otherwise use trace_id or request_id",
    )
    question: Optional[str] = Field(None, description="Original question (optional)")
    answer_snippet: Optional[str] = Field(None, description="Snippet of answer being rated (optional)")
    rating: Literal["thumbs_up", "thumbs_down"] = Field(..., description="Thumbs up or down")
    feedback_type: Optional[str] = Field(
        None,
        description="Predefined type: not_relevant, biased, not_factual, incomplete_instructions, unsafe, style_tone, other",
    )
    comment: Optional[str] = Field(None, description="Additional free-text feedback (optional)")


def submit_langsmith_feedback(
    agent_graph_run_id: str,
    rating: Literal["thumbs_up", "thumbs_down"],
    feedback_type: Optional[str],
    comment: Optional[str],
) -> bool:
    """Submit feedback to LangSmith for the agent_graph run (root run from orchestrator).
    Attaches feedback to the agent_graph node, not child runs. Returns True if sent, False if skipped."""
    if not has_langsmith_credentials():
        return False
    try:
        client = Client()
        score = 1.0 if rating == "thumbs_up" else -1.0
        client.create_feedback(
            run_id=agent_graph_run_id,
            key=LANGSMITH_FEEDBACK_KEY,
            score=score,
            value=feedback_type or rating,
            comment=comment,
        )
        return True
    except Exception as e:
        logging.warning("langsmith create_feedback failed: %s", e)
        return False
