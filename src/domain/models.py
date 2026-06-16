"""Typed domain models shared by the workflow and UI.

These models keep Streamlit and LangGraph from passing raw dicts across every
module seam. Agents can still use dict state internally while the public
workflow interface stays explicit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class AgentFailure:
    """Structured failure returned by workflow operations."""

    stage: str
    message: str
    recoverable: bool = True


@dataclass
class WorkflowResult(Generic[T]):
    """Result envelope for UI-facing workflow calls."""

    ok: bool
    value: T | None = None
    failure: AgentFailure | None = None

    @classmethod
    def success(cls, value: T) -> "WorkflowResult[T]":
        return cls(ok=True, value=value)

    @classmethod
    def error(
        cls,
        stage: str,
        message: str,
        recoverable: bool = True,
    ) -> "WorkflowResult[T]":
        return cls(
            ok=False,
            failure=AgentFailure(
                stage=stage,
                message=message,
                recoverable=recoverable,
            ),
        )


@dataclass
class ResearchSearchResult:
    """Planner + retrieval output for a user research topic."""

    query: str
    subtopics: list[dict[str, Any]] = field(default_factory=list)
    papers: list[Any] = field(default_factory=list)


@dataclass
class PaperSelection:
    """Selected papers and generated artifacts for the reading workflow."""

    papers: list[Any]
    selected_ids: set[str]
    summaries: dict[str, str] = field(default_factory=dict)

    @property
    def selected_papers(self) -> list[Any]:
        return [p for p in self.papers if paper_uid(p) in self.selected_ids]


def paper_uid(paper: Any) -> str:
    """Stable UI/workflow identifier for a paper-like object."""

    arxiv_id = getattr(paper, "arxiv_id", "")
    if arxiv_id:
        return str(arxiv_id)
    title = getattr(paper, "title", "")
    return f"no-id:{abs(hash(title))}"
