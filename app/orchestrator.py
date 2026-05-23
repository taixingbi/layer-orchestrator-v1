"""Re-export pipeline for backward compatibility."""

from .pipeline import answer_query_sync, format_error, stream_answer_query

__all__ = ["stream_answer_query", "answer_query_sync", "format_error"]
