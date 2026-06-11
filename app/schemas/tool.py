"""Tool call argument schemas."""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class UserProfileToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    collection_base: Optional[str] = None
    conversation_id: Optional[str] = None
    k: Optional[int] = None
    k_max: Optional[int] = None
    stream: bool = True


class GithubRepoSearchToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    repo: Optional[str] = None
    conversation_id: Optional[str] = None
    stream: bool = True


class WebSearchToolArgs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    question: str
    max_results: Optional[int] = Field(default=None, ge=1, le=20)


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    answer: str = ""
    answer_blocks: list = Field(default_factory=list)
    answer_notes: list = Field(default_factory=list)
    answer_format: str = "text"
    citations: list = Field(default_factory=list)
    follow_up_questions: list = Field(default_factory=list)
    usage: Optional[Dict[str, Any]] = None
    latency_ms: Optional[Dict[str, Any]] = None
    rag: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
