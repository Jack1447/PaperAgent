"""Review Agent — 对论文进行审稿式分析"""
import asyncio
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent
from src.corpus.paper_corpus import PaperCorpus


class ReviewAgent(BaseAgent):
    """论文审稿 Agent —— 多维度审阅分析"""

    def __init__(self, corpus: PaperCorpus | None = None):
        super().__init__(name="Review", use_fast_llm=False)
        self.corpus = corpus or PaperCorpus()

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        对选定论文生成审稿报告

        state 需要包含:
        - selected_paper_id: arXiv ID
        - paper_summary: 已生成的总结（来自前端 state，可选）
        - paper_abstract: 论文摘要（可选）
        """
        arxiv_id = state.get("selected_paper_id", "")
        if not arxiv_id:
            return {"review": "请先选择一篇论文。"}

        title = state.get("paper_title", "")
        paper_summary = state.get("paper_summary", "")
        paper_abstract = state.get("paper_abstract", "")

        chunks_text = ""
        is_real_arxiv = arxiv_id and not arxiv_id.startswith("no-id:")

        # 1. Try SimpleStore chunks (from previous summarize — already downloaded & chunked)
        if is_real_arxiv:
            chunks = self.corpus.retrieve_chunks(
                arxiv_id, "introduction method experiment conclusion", top_k=12
            )
            if chunks:
                chunks_text = "\n\n".join(c["text"][:3000] for c in chunks[:8])

        # 2. Fallback: corpus summary (persisted by summarize agent)
        if not chunks_text:
            summary = await asyncio.to_thread(self.corpus.get_summary, arxiv_id)
            if summary:
                chunks_text = summary[:6000]

        # 3. Fallback: paper_summary from web state
        if not chunks_text and paper_summary:
            chunks_text = paper_summary[:6000]

        # 4. Fallback: paper_abstract from web state
        if not chunks_text and paper_abstract:
            chunks_text = f"标题: {title}\n\n摘要: {paper_abstract[:6000]}"

        if not chunks_text:
            return {"review": "无法获取论文内容进行审稿。"}

        # Get title from metadata if not already set
        if not title:
            paper_info = self.corpus.get_paper_metadata(arxiv_id)
            title = paper_info.get("title", "") if paper_info else ""

        # Build prompt
        system_prompt = get_prompt_by_name("review.system")
        task_prompt = (
            get_prompt_by_name("review.task")
            .replace("{title}", title[:200] if title else "")
            .replace("{chunks}", chunks_text[:8000])
        )

        review = await self.invoke_llm(task_prompt, system=system_prompt)

        return {"review": review}
