"""Typed LangGraph state for PaperAgent workflows."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def merge_lists(left: list | None, right: list | None) -> list:
    """LangGraph reducer for append-only lists."""

    return list(left or []) + list(right or [])


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """LangGraph reducer for map-like outputs such as summaries."""

    return {**(left or {}), **(right or {})}


class WorkflowError(TypedDict, total=False):
    node: str
    message: str
    recoverable: bool


class AgentState(TypedDict, total=False):
    """Global workflow state.

    The graph still accepts plain dictionaries from callers, but internal nodes
    now have an explicit interface and reducers for parallel outputs.
    """

    # User input
    user_query: str
    selected_paper_id: str
    paper_title: str
    user_question: str

    # Planner
    subtopics: list[dict[str, Any]]
    plan_quality_pass: bool
    plan_retry_count: int
    plan_feedback: str

    # Search
    papers: list[Any]
    search_quality_pass: bool
    search_retry_count: int
    reflection_feedback: str

    # Summarize
    paper: Any
    summaries: Annotated[dict[str, str], merge_dicts]
    summary_quality_pass: bool

    # Reading
    chat_history: list[dict[str, str]]
    answer: str

    # Review
    review: str

    # Human feedback
    human_feedback: str
    human_notes: str

    # Errors
    errors: Annotated[list[WorkflowError], merge_lists]
    fatal_error: bool
