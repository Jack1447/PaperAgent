"""
Summarize Agent
两阶段总结：
  Stage 1: 读 title + abstract + intro + conclusion → 整体摘要
  Stage 2: ChromaDB 检索 method/experiment chunk → 补充技术细节
"""
import asyncio
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent
from src.corpus.paper_corpus import PaperCorpus


class SummarizeAgent(BaseAgent):
    """论文总结 Agent —— 两阶段结构化摘要生成"""

    def __init__(self, corpus: PaperCorpus | None = None):
        super().__init__(name="Summarize", use_fast_llm=False)
        self.corpus = corpus or PaperCorpus()

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        对论文列表中的每篇论文生成摘要
        单篇论文模式（由 LangGraph Send 并行调用）
        """
        paper = state.get("paper")
        if not paper:
            return {"summaries": {}}

        arxiv_id = paper.arxiv_id if hasattr(paper, "arxiv_id") else paper.get("arxiv_id", "")
        title = paper.title if hasattr(paper, "title") else paper.get("title", "")
        authors = paper.authors if hasattr(paper, "authors") else paper.get("authors", [])

        if isinstance(authors, list):
            author_str = ", ".join(a for a in authors if isinstance(a, str))
            if len(authors) > 5:
                author_str += " et al."
        else:
            author_str = str(authors)

        # 没有 arXiv ID 则降级为简短摘要
        abstract = getattr(paper, "abstract", "")
        if not arxiv_id or arxiv_id.startswith("no-id:"):
            summary = await self._fallback_summary(title, author_str, abstract)
            await asyncio.to_thread(self.corpus.save_summary, arxiv_id, title, summary, {"authors": author_str})
            return {"summaries": {arxiv_id or title: summary}}

        cached_summary = await asyncio.to_thread(self.corpus.get_summary, arxiv_id)
        if cached_summary:
            print(f"  [Summarize] 已缓存: {title[:40]}...")
            return {"summaries": {arxiv_id: cached_summary}}

        # 1. 下载并解析 PDF
        print(f"  [Summarize] 正在处理: {title[:60]}...")
        paper_text, chunked = await asyncio.to_thread(
            self.corpus.prepare_summary_inputs, arxiv_id
        )

        if not paper_text.full_text:
            # PDF 解析失败，用摘要生成简短总结（也存入 corpus）
            summary = await self._fallback_summary(title, author_str, abstract)
            await asyncio.to_thread(self.corpus.save_summary, arxiv_id, title, summary, {"authors": author_str})
        else:
            # 2. 存储全文 chunk 到 Paper Corpus
            await asyncio.to_thread(
                self.corpus.store_paper_chunks, arxiv_id, paper_text
            )

            # 3. Stage 1: 整体摘要
            system_prompt = get_prompt_by_name("summarize.system")
            stage1_prompt = (
                get_prompt_by_name("summarize.stage1")
                .replace("{title}", title)
                .replace("{authors}", author_str)
                .replace("{chunks}", chunked["stage1"])
            )

            summary = await self.invoke_llm(stage1_prompt, system=system_prompt)

            # 5. Stage 2: 技术细节补充
            if chunked["stage2"].strip():
                await asyncio.to_thread(
                    self.corpus.store_detail_chunks, arxiv_id, chunked["stage2"]
                )

                stage2_prompt = (
                    get_prompt_by_name("summarize.stage2")
                    .replace("{retrieved_chunks}", chunked["stage2"][:3000])
                )
                detail = await self.invoke_llm(stage2_prompt, system=system_prompt)
                summary += "\n\n" + detail

        # 6. 持久化
        await asyncio.to_thread(
            self.corpus.save_summary,
            arxiv_id, title, summary,
            {"authors": author_str},
        )
        await asyncio.to_thread(
            self.corpus.save_paper_metadata,
            arxiv_id=arxiv_id,
            title=title,
            authors=list(getattr(paper, "authors", [])) if not isinstance(getattr(paper, "authors", []), list) else getattr(paper, "authors", []),
            abstract=getattr(paper, "abstract", ""),
            url=getattr(paper, "url", f"https://arxiv.org/abs/{arxiv_id}"),
            published=getattr(paper, "published", ""),
            citations=getattr(paper, "citations", 0),
            summary=summary,
        )

        return {
            "summaries": {arxiv_id: summary},
        }

    async def _fallback_summary(
        self, title: str, authors: str, abstract: str
    ) -> str:
        """PDF 解析失败时，用 arXiv 摘要生成简短总结"""
        if not abstract:
            return f"## {title}\n\n(无法获取论文全文，请手动阅读)"

        prompt = (
            f"请根据以下论文信息生成结构化摘要（用中文）:\n\n"
            f"标题: {title}\n"
            f"作者: {authors}\n"
            f"摘要: {abstract[:3000]}\n\n"
            f"格式:\n"
            f"## 核心贡献\n"
            f"(一句话)\n\n"
            f"## 研究背景\n"
            f"(1-2句)\n\n"
            f"## 方法\n"
            f"(简要描述)\n\n"
            f"## 创新点\n"
            f"(1-2个)\n\n"
            f"## 实验结果\n"
            f"(如摘要提及，简述关键数据)\n\n"
            f"## 结论\n"
            f"(如摘要提及，简述结论)\n\n"
            f"## 局限性\n"
            f"(1句话)\n"
        )
        return await self.invoke_llm(prompt)
