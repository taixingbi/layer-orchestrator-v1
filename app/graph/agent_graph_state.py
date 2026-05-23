"""Shared LangGraph state type for the RAG agent."""

from langgraph.graph.message import MessagesState


class AgentState(MessagesState, total=False):
    retry_count: int
    judge_passed: bool
