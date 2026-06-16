"""
Search Agent
对 Planner 输出的子主题执行论文检索
"""
from typing import Any

from src.agents.base import BaseAgent
from src.retrieval.literature_retrieval import LiteratureRetrieval


class SearchAgent(BaseAgent):
    """论文检索 Agent —— 多子主题轮询搜索，去重合并"""

    def __init__(self, retrieval: LiteratureRetrieval | None = None):
        super().__init__(name="Search", use_fast_llm=True)
        self.retrieval = retrieval or LiteratureRetrieval()

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        subtopics = state.get("subtopics", [])
        papers = self.retrieval.retrieve(
            subtopics=subtopics,
            fallback_query=state.get("user_query", ""),
        )
        return {"papers": papers}

    async def run_stream(self, state: dict[str, Any]):
        """Async generator that yields papers one by one."""
        subtopics = state.get("subtopics", [])
        fallback = state.get("user_query", "")
        max_papers = state.get("max_papers", 15)

        self.retrieval.max_papers = max_papers
        for paper in self.retrieval.retrieve_stream(
            subtopics=subtopics,
            fallback_query=fallback,
        ):
            yield paper
