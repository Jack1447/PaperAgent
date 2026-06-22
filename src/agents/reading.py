"""
Reading Agent
基于 ChromaDB 检索 + 多轮对话 + 引用溯源
"""
import asyncio
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent
from src.corpus.paper_corpus import PaperCorpus


class ReadingAgent(BaseAgent):
    """论文辅助阅读 Agent —— 多轮深度问答"""

    def __init__(self, corpus: PaperCorpus | None = None):
        super().__init__(name="Reading", use_fast_llm=False)
        self.corpus = corpus or PaperCorpus()

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        基于论文内容回答用户问题

        state 需要包含:
        - selected_paper_id: 当前选中的 arXiv ID
        - user_question: 用户最新问题
        - chat_history: 对话历史 (list of {role, content})
        - paper_abstract: 论文摘要（来自前端 state，可选）
        - paper_summary: 论文总结（来自前端 state，可选）
        """
        arxiv_id = state.get("selected_paper_id", "")
        question = state.get("user_question", "")
        chat_history = state.get("chat_history", [])
        paper_abstract = state.get("paper_abstract", "")
        paper_summary = state.get("paper_summary", "")
        image_data_url = state.get("image_data_url", "")

        if not arxiv_id:
            return {"answer": "请先选择一篇论文。"}

        if not question and not image_data_url:
            return {"answer": "请输入你的问题。"}

        if not question:
            question = "请描述并解释这张图片。"

        # 1. 获取论文元数据
        paper_info = self.corpus.get_paper_metadata(arxiv_id)
        title = paper_info.get("title", "") if paper_info else state.get("paper_title", "")

        # 2. Paper Corpus 语义检索最相关的 chunks
        chunks = []
        if arxiv_id and not arxiv_id.startswith("no-id:"):
            chunks = await asyncio.to_thread(
                self.corpus.retrieve_chunks, arxiv_id, question, 5
            )

        # 3. Build fallback context — merge all available sources
        if not chunks:
            fallback_parts = []
            # Try corpus summary (persisted in chroma)
            summary = await asyncio.to_thread(self.corpus.get_summary, arxiv_id)
            if summary:
                fallback_parts.append(f"## 论文总结\n{summary[:4000]}")
            if paper_summary:
                fallback_parts.append(f"## 论文总结\n{paper_summary[:4000]}")
            if paper_abstract:
                fallback_parts.append(f"## 论文摘要\n{paper_abstract[:4000]}")
            if title:
                fallback_parts.insert(0, f"标题: {title}")
            for i, fp in enumerate(fallback_parts):
                chunks.append({
                    "text": fp,
                    "metadata": {"chunk_id": f"fallback_{i}", "section": "fallback"},
                })

        if not chunks:
            return {
                "answer": "论文内容尚未就绪。总结正在生成中，请等总结面板出现内容后再进行提问。",
            }

        # 3. 组装上下文
        chunks_text = "\n\n---\n\n".join(
            self._format_chunk_for_prompt(c)
            for c in chunks
        )

        # 格式化对话历史
        history_text = ""
        for msg in chat_history[-6:]:  # 最近 6 条
            role = "用户" if msg.get("role") == "user" else "助手"
            history_text += f"{role}: {msg.get('content', '')[:300]}\n"

        # 4. 组装 Prompt
        context_prompt = (
            get_prompt_by_name("reading.context_template")
            .replace("{title}", title)
            .replace("{authors}", str(paper_info.get("authors", "")) if paper_info else "")
            .replace("{chunks}", chunks_text[:6000])
            .replace("{history}", history_text)
            .replace("{question}", question)
        )

        system_prompt = get_prompt_by_name("reading.system")

        # 5. 调用 LLM —— 若用户上传了图片，组装多模态消息
        if image_data_url:
            content = [
                {"type": "text", "text": context_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]
            answer = await self.llm.chat(
                messages=[{"role": "user", "content": content}],
                system=system_prompt,
            )
        else:
            answer = await self.invoke_llm(context_prompt, system=system_prompt)

        return {"answer": answer}

    def _format_chunk_for_prompt(self, chunk: dict[str, Any]) -> str:
        text = chunk.get("text", "")[:2000]
        return text
