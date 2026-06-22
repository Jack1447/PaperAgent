"""UI-facing research workflow facade.

This module is the external seam for the product workflow. Streamlit should call
this module instead of importing individual agents directly.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, AsyncGenerator

from src.domain.models import (
    PaperSelection,
    ResearchSearchResult,
    WorkflowResult,
    paper_uid,
)


class ResearchWorkflow:
    """Paper search, selection, summarization, and reading workflow."""

    async def plan(self, query: str) -> WorkflowResult[list[dict]]:
        """Run only the planner, return subtopics."""
        try:
            from src.agents.planner import PlannerAgent

            planner = PlannerAgent()
            plan = await planner.run({"user_query": query})
            subtopics = plan.get("subtopics", [])
            return WorkflowResult.success(subtopics)
        except Exception as exc:
            return WorkflowResult.error("plan", workflow_error_message(exc))

    async def search(
        self, query: str, max_papers: int = 15
    ) -> WorkflowResult[ResearchSearchResult]:
        query = query.strip()
        if not query:
            return WorkflowResult.error("search", "请输入研究主题。")

        try:
            from src.agents.planner import PlannerAgent
            from src.agents.search import SearchAgent

            planner = PlannerAgent()
            plan = await planner.run({"user_query": query})
            subtopics = plan.get("subtopics", [])

            search = SearchAgent()
            search.retrieval.max_papers = max_papers
            result = await search.run({
                "user_query": query,
                "subtopics": subtopics,
            })
            return WorkflowResult.success(
                ResearchSearchResult(
                    query=query,
                    subtopics=subtopics,
                    papers=result.get("papers", []),
                )
            )
        except Exception as exc:
            return WorkflowResult.error("search", workflow_error_message(exc))

    async def search_stream(
        self, query: str, max_papers: int = 15
    ) -> AsyncGenerator[Any, None]:
        """Stream papers one by one as they are retrieved."""
        from src.agents.planner import PlannerAgent
        from src.agents.search import SearchAgent

        planner = PlannerAgent()
        plan = await planner.run({"user_query": query})
        subtopics = plan.get("subtopics", [])

        search = SearchAgent()
        async for paper in search.run_stream({
            "user_query": query,
            "subtopics": subtopics,
            "max_papers": max_papers,
        }):
            yield paper

    async def add_arxiv_paper(self, link_or_id: str) -> WorkflowResult[Any]:
        arxiv_id = parse_arxiv_link(link_or_id)
        if not arxiv_id:
            return WorkflowResult.error(
                "add_paper",
                "无法解析 arXiv ID，请提供 arXiv 链接或 ID。",
            )

        try:
            from src.tools.arxiv_client import ArxivClient

            client = ArxivClient()
            paper = await asyncio.to_thread(client.get_paper_by_id, arxiv_id)
            if not paper:
                return WorkflowResult.error(
                    "add_paper",
                    "无法获取该论文，请检查 arXiv ID。",
                )
            return WorkflowResult.success(paper)
        except Exception as exc:
            return WorkflowResult.error("add_paper", workflow_error_message(exc))

    async def summarize_selection(
        self,
        selection: PaperSelection,
        existing: dict[str, str] | None = None,
    ) -> WorkflowResult[dict[str, str]]:
        summaries = dict(existing or {})
        selected = selection.selected_papers
        if not selected:
            return WorkflowResult.error("summarize", "请先选择至少一篇论文。")

        try:
            from src.agents.summarize import SummarizeAgent

            for paper in selected:
                uid = paper_uid(paper)
                if uid in summaries:
                    continue
                agent = SummarizeAgent()
                result = await agent.run({"paper": paper})
                generated = result.get("summaries", {})
                if uid in generated:
                    summaries[uid] = generated[uid]
                elif len(generated) == 1:
                    summaries[uid] = next(iter(generated.values()))
                else:
                    summaries.update(generated)
            return WorkflowResult.success(summaries)
        except Exception as exc:
            return WorkflowResult.error("summarize", workflow_error_message(exc))

    async def ask_paper(
        self,
        paper_id: str,
        paper_title: str,
        paper_abstract: str,
        paper_summary: str,
        question: str,
        chat_history: list[dict[str, str]],
        image_data_url: str = "",
    ) -> WorkflowResult[str]:
        try:
            from src.agents.reading import ReadingAgent

            agent = ReadingAgent()
            result = await agent.run({
                "selected_paper_id": paper_id,
                "paper_title": paper_title,
                "paper_abstract": paper_abstract,
                "paper_summary": paper_summary,
                "user_question": question,
                "chat_history": chat_history,
                "image_data_url": image_data_url,
            })
            return WorkflowResult.success(result.get("answer", ""))
        except Exception as exc:
            return WorkflowResult.error("reading", workflow_error_message(exc))

    async def review_paper(
        self,
        paper_id: str,
        paper_title: str,
        paper_abstract: str = "",
        paper_summary: str = "",
    ) -> WorkflowResult[str]:
        try:
            from src.agents.review import ReviewAgent

            agent = ReviewAgent()
            result = await agent.run({
                "selected_paper_id": paper_id,
                "paper_title": paper_title,
                "paper_abstract": paper_abstract,
                "paper_summary": paper_summary,
            })
            return WorkflowResult.success(result.get("review", ""))
        except Exception as exc:
            return WorkflowResult.error("review", workflow_error_message(exc))

    async def compare_papers(
        self,
        papers_to_compare: list[dict[str, str]],
    ) -> WorkflowResult[str]:
        """对多篇已生成摘要的论文进行对比分析。

        papers_to_compare: [{title, summary}, ...]
        """
        if len(papers_to_compare) < 2:
            return WorkflowResult.error("compare", "请至少选择两篇论文进行对比分析。")

        try:
            from src.agents.compare import CompareAgent

            agent = CompareAgent()
            result = await agent.run({"papers_to_compare": papers_to_compare})
            return WorkflowResult.success(result.get("comparison", ""))
        except Exception as exc:
            return WorkflowResult.error("compare", workflow_error_message(exc))

    async def get_recommendation(
        self,
        signals: str,
        old_memory: str,
    ) -> WorkflowResult[dict[str, str]]:
        """提炼用户记忆并生成个性化推荐。

        返回 {"memory": 更新后的记忆文档, "recommendation": 推荐文本}。
        记忆文档的持久化由调用方负责。
        """
        try:
            from src.agents.recommend import RecommendAgent

            agent = RecommendAgent()
            result = await agent.run({"signals": signals, "old_memory": old_memory})
            return WorkflowResult.success({
                "memory": result.get("memory", ""),
                "recommendation": result.get("recommendation", ""),
            })
        except Exception as exc:
            return WorkflowResult.error("recommend", workflow_error_message(exc))


def parse_arxiv_link(link: str) -> str | None:
    """Extract arXiv ID from an arXiv URL, PDF URL, or raw ID."""

    text = link.strip()
    m = re.search(r"arxiv\.org/abs/([\w.-]+)", text, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r"arxiv\.org/pdf/([\w.-]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(".pdf", "")
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", text):
        return text
    return None


def workflow_error_message(exc: Exception) -> str:
    """Convert common runtime exceptions into user-facing messages."""

    name = exc.__class__.__name__
    if name == "LLMConfigError":
        return f"LLM 配置不完整：{exc}"
    if isinstance(exc, ModuleNotFoundError):
        return f"缺少依赖 `{exc.name}`，请先安装 requirements.txt 中的依赖。"
    return str(exc)
