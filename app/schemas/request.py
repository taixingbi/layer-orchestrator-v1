"""HTTP request body models."""

from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from ..core.rewrite import normalize_history_turns


class HistoryTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AnswerBody(BaseModel):
    question: str
    stream: bool = Field(
        default=True,
        description="true (default) → SSE (text/event-stream); false → single aggregated JSON object",
    )
    history: List[HistoryTurn] = Field(default_factory=list)
    conversation_id: Optional[str] = Field(
        default=None,
        max_length=256,
        description=(
            "Client-owned thread id (optional). Omit, null, or whitespace → server assigns "
            "conv_<uuidhex>; response includes effective conversation_id and is_new_conversation."
        ),
    )

    @field_validator("conversation_id", mode="before")
    @classmethod
    def _blank_conversation_id_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        raise ValueError("conversation_id must be a string or null")


class EvalRouterBody(BaseModel):
    question: str
    expected_route: Optional[Literal["rag", "direct_reply", "clarify", "reject", "tool"]] = None
    conversation_id: Optional[str] = Field(
        default=None,
        max_length=256,
        description=(
            "Client-owned thread id (optional). Omit, null, or whitespace → server assigns "
            "conv_<uuidhex>; response includes effective conversation_id and is_new_conversation."
        ),
    )
    router_model: Optional[str] = Field(default=None, max_length=256)
    router_temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    router_prompt_version: Optional[str] = Field(
        default=None,
        max_length=256,
        pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$",
    )
    router_prompt_override: Optional[str] = None
    history: List[HistoryTurn] = Field(default_factory=list)

    @field_validator("router_model", "router_prompt_version", "conversation_id", mode="before")
    @classmethod
    def _blank_router_str_to_none(cls, v: object) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            s = v.strip()
            return s if s else None
        raise ValueError("must be a string or null")


def history_from_answer_body(body: AnswerBody) -> List[Tuple[str, str]]:
    return normalize_history_turns([(t.role, t.content) for t in body.history])


def history_from_eval_body(body: EvalRouterBody) -> List[Tuple[str, str]]:
    return normalize_history_turns([(t.role, t.content) for t in body.history])
