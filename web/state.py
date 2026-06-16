"""Global application state (single-user, in-memory).

State is persisted to data/session.json so it survives server restarts
and page refreshes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

# Project root for data directory
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SESSION_PATH = os.path.join(_PROJECT_ROOT, "data", "session.json")


def _paper_to_serializable(paper: Any) -> dict:
    """Extract known attributes from a paper-like object into a plain dict."""
    return {
        "arxiv_id": getattr(paper, "arxiv_id", ""),
        "title": getattr(paper, "title", ""),
        "authors": getattr(paper, "authors", []),
        "abstract": getattr(paper, "abstract", ""),
        "published": getattr(paper, "published", ""),
        "citations": getattr(paper, "citations", 0),
        "sources": getattr(paper, "sources", []),
        "retrieval_score": getattr(paper, "retrieval_score", None),
        "retrieval_reasons": getattr(paper, "retrieval_reasons", []),
        "url": getattr(paper, "url", ""),
    }


def _dict_to_paper(data: dict) -> SimpleNamespace:
    """Reconstruct a paper-like object from a serialized dict."""
    return SimpleNamespace(**data)


@dataclass
class AppState:
    query: str = ""
    papers: list[Any] = field(default_factory=list)
    subtopics: list[dict] = field(default_factory=list)
    selected_ids: set[str] = field(default_factory=set)
    summaries: dict[str, str] = field(default_factory=dict)
    chat_by_paper: dict[str, list[dict]] = field(default_factory=dict)
    review_by_paper: dict[str, str] = field(default_factory=dict)
    manual_links: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.query = ""
        self.papers = []
        self.subtopics = []
        self.selected_ids = set()
        self.summaries = {}
        self.chat_by_paper = {}
        self.review_by_paper = {}
        self.manual_links = []

    # ── Persistence ──

    def save(self) -> None:
        os.makedirs(os.path.dirname(_SESSION_PATH), exist_ok=True)
        data = {
            "query": self.query,
            "subtopics": self.subtopics,
            "papers": [_paper_to_serializable(p) for p in self.papers],
            "selected_ids": list(self.selected_ids),
            "summaries": self.summaries,
            "chat_by_paper": self.chat_by_paper,
            "review_by_paper": self.review_by_paper,
            "manual_links": self.manual_links,
        }
        tmp_path = _SESSION_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, _SESSION_PATH)  # atomic

    @classmethod
    def load(cls) -> "AppState":
        state = cls()
        if not os.path.exists(_SESSION_PATH):
            return state
        try:
            with open(_SESSION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            state.query = data.get("query", "")
            state.subtopics = data.get("subtopics", [])
            state.papers = [_dict_to_paper(p) for p in data.get("papers", [])]
            state.selected_ids = set(data.get("selected_ids", []))
            state.summaries = data.get("summaries", {})
            state.chat_by_paper = data.get("chat_by_paper", {})
            state.review_by_paper = data.get("review_by_paper", {})
            state.manual_links = data.get("manual_links", [])
        except Exception:
            pass  # corrupted file, start fresh
        return state


# Load from disk on module import
state = AppState.load()
