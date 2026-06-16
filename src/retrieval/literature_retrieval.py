"""Literature retrieval module.

This module owns source adapters, normalization, deduplication, and ranking.
SearchAgent delegates retrieval here.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from config.settings import get_search_config


class PaperSource(Protocol):
    name: str
    def search(self, query: str) -> list[Any]: ...


@dataclass
class RetrievalQuery:
    topic_name: str
    keyword: str


class ArxivSource:
    name = "arxiv"

    def __init__(self):
        from src.tools.arxiv_client import ArxivClient
        self.client = ArxivClient()

    def search(self, query: str) -> list[Any]:
        return self.client.search(query)


class ScholarSource:
    name = "scholar"

    def __init__(self, api_key: str = "", base_url: str = "", arxiv_client=None):
        from src.tools.scholar import ScholarClient
        self.client = ScholarClient(api_key=api_key, base_url=base_url, arxiv_client=arxiv_client)

    def search(self, query: str) -> list[Any]:
        return self.client.search(query)


class LiteratureRetrieval:
    """Retrieve and rank papers across literature sources."""

    SOURCE_WEIGHTS = {
        "arxiv": 2.0,
        "scholar": 1.6,
    }

    def __init__(
        self,
        sources: list[PaperSource] | None = None,
        max_papers: int | None = None,
    ):
        self.config = get_search_config()
        self.sources = sources if sources is not None else self._default_sources()
        self.max_papers = max_papers or self.config.get("max_final_papers", 15)

    def retrieve_stream(
        self,
        subtopics: list[dict[str, Any]],
        fallback_query: str = "",
    ):
        """Generator that yields papers one by one as they are retrieved."""
        queries = self._build_queries(subtopics, fallback_query)
        by_key: dict[str, Any] = {}
        count = 0

        for query in queries:
            if count >= self.max_papers:
                break
            for source in self.sources:
                if count >= self.max_papers:
                    break
                for paper in source.search(query.keyword):
                    if count >= self.max_papers:
                        break
                    self._annotate_paper(paper, source.name, query)
                    key = self._dedupe_key(paper)
                    existing = by_key.get(key)
                    if existing is None:
                        by_key[key] = paper
                        score, reasons = self._score_paper(paper)
                        setattr(paper, "retrieval_score", score)
                        setattr(paper, "retrieval_reasons", reasons)
                        count += 1
                        yield paper
                    else:
                        by_key[key] = self._merge_paper(existing, paper)

    def retrieve(
        self,
        subtopics: list[dict[str, Any]],
        fallback_query: str = "",
    ) -> list[Any]:
        queries = self._build_queries(subtopics, fallback_query)
        by_key: dict[str, Any] = {}

        for query in queries:
            for source in self.sources:
                for paper in source.search(query.keyword):
                    self._annotate_paper(paper, source.name, query)
                    key = self._dedupe_key(paper)
                    existing = by_key.get(key)
                    if existing is None:
                        by_key[key] = paper
                    else:
                        by_key[key] = self._merge_paper(existing, paper)

        papers = list(by_key.values())
        for paper in papers:
            score, reasons = self._score_paper(paper)
            setattr(paper, "retrieval_score", score)
            setattr(paper, "retrieval_reasons", reasons)
        papers.sort(key=self._rank_key, reverse=True)
        return papers[: self.max_papers]

    def _default_sources(self) -> list[PaperSource]:
        sources: list[PaperSource] = []
        arxiv = ArxivSource()
        sources.append(arxiv)

        scholar_key = os.getenv("SCHOLAR_API_KEY", "")
        scholar_url = os.getenv("SCHOLAR_BASE_URL", "")
        if scholar_key:
            sources.append(ScholarSource(api_key=scholar_key, base_url=scholar_url, arxiv_client=arxiv.client))

        return sources

    def _build_queries(
        self,
        subtopics: list[dict[str, Any]],
        fallback_query: str,
    ) -> list[RetrievalQuery]:
        queries: list[RetrievalQuery] = []
        for topic in subtopics:
            name = str(topic.get("name", "topic"))
            for keyword in topic.get("keywords", []):
                keyword = str(keyword).strip()
                if keyword:
                    queries.append(RetrievalQuery(topic_name=name, keyword=keyword))

        if not queries and fallback_query.strip():
            queries.append(
                RetrievalQuery(topic_name="main topic", keyword=fallback_query.strip())
            )
        return queries

    def _annotate_paper(
        self,
        paper: Any,
        source_name: str,
        query: RetrievalQuery,
    ) -> None:
        sources = set(getattr(paper, "sources", []) or [])
        sources.add(source_name)
        setattr(paper, "sources", sorted(sources))
        setattr(paper, "matched_topic", query.topic_name)
        setattr(paper, "matched_keyword", query.keyword)

        arxiv_id = getattr(paper, "arxiv_id", "")
        if arxiv_id:
            setattr(paper, "arxiv_id", normalize_arxiv_id(arxiv_id))

    def _dedupe_key(self, paper: Any) -> str:
        arxiv_id = getattr(paper, "arxiv_id", "")
        if arxiv_id:
            return f"arxiv:{normalize_arxiv_id(arxiv_id)}"
        title = normalize_title(getattr(paper, "title", ""))
        return f"title:{title}"

    def _merge_paper(self, left: Any, right: Any) -> Any:
        left_sources = set(getattr(left, "sources", []) or [])
        right_sources = set(getattr(right, "sources", []) or [])
        setattr(left, "sources", sorted(left_sources | right_sources))

        if not getattr(left, "arxiv_id", "") and getattr(right, "arxiv_id", ""):
            setattr(left, "arxiv_id", getattr(right, "arxiv_id"))
        if not getattr(left, "abstract", "") and getattr(right, "abstract", ""):
            setattr(left, "abstract", getattr(right, "abstract"))
        if not getattr(left, "pdf_url", "") and getattr(right, "pdf_url", ""):
            setattr(left, "pdf_url", getattr(right, "pdf_url"))
        if not getattr(left, "url", "") and getattr(right, "url", ""):
            setattr(left, "url", getattr(right, "url"))
        if getattr(right, "citations", 0) > getattr(left, "citations", 0):
            setattr(left, "citations", getattr(right, "citations", 0))
        return left

    def _score_paper(self, paper: Any) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        sources = getattr(paper, "sources", []) or []
        source_score = sum(self.SOURCE_WEIGHTS.get(s, 1.0) for s in sources)
        if source_score:
            score += source_score
            reasons.append(f"sources:{','.join(sources)}")

        relevance = self._keyword_relevance(paper)
        if relevance:
            score += relevance * 2.0
            reasons.append(f"keyword_match:{relevance}")

        citations = int(getattr(paper, "citations", 0) or 0)
        if citations:
            citation_score = min(3.0, citations ** 0.5 / 10)
            score += citation_score
            reasons.append(f"citations:{citations}")

        year = self._paper_year(paper)
        if year:
            freshness = self._freshness_score(year)
            score += freshness
            reasons.append(f"year:{year}")

        if getattr(paper, "arxiv_id", ""):
            score += 1.0
            reasons.append("arxiv_available")
        if getattr(paper, "pdf_url", ""):
            score += 0.5
            reasons.append("pdf_available")
        if getattr(paper, "abstract", ""):
            score += 0.5
            reasons.append("abstract_available")

        return round(score, 4), reasons

    def _keyword_relevance(self, paper: Any) -> int:
        keyword = getattr(paper, "matched_keyword", "") or ""
        if not keyword:
            return 0
        haystack = normalize_title(
            f"{getattr(paper, 'title', '')} {getattr(paper, 'abstract', '')}"
        )
        terms = [t for t in re.findall(r"[a-z0-9]+", keyword.lower()) if len(t) > 2]
        if not terms:
            return 0
        return sum(1 for term in set(terms) if term in haystack)

    def _paper_year(self, paper: Any) -> int | None:
        published = str(getattr(paper, "published", "") or "")
        match = re.search(r"\b(19|20)\d{2}\b", published)
        if not match:
            return None
        return int(match.group())

    def _freshness_score(self, year: int) -> float:
        age = max(0, date.today().year - year)
        if age <= 2:
            return 1.5
        if age <= 5:
            return 1.0
        if age <= 10:
            return 0.5
        return 0.0

    def _rank_key(self, paper: Any) -> tuple[float, int, int, str]:
        score = float(getattr(paper, "retrieval_score", 0.0) or 0.0)
        citations = int(getattr(paper, "citations", 0) or 0)
        has_arxiv = 1 if getattr(paper, "arxiv_id", "") else 0
        title = normalize_title(getattr(paper, "title", ""))
        return (score, citations, has_arxiv, title)


def normalize_arxiv_id(arxiv_id: str) -> str:
    cleaned = (
        arxiv_id.replace("https://arxiv.org/abs/", "")
        .replace("https://arxiv.org/pdf/", "")
        .replace(".pdf", "")
        .strip()
    )
    return re.sub(r"v\d+$", "", cleaned)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())
