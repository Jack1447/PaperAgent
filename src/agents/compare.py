"""Compare Agent — 对多篇论文进行对比分析，生成对比表格 + 综述"""
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent


class CompareAgent(BaseAgent):
    """多论文对比 Agent —— 接收多篇已生成摘要的论文，输出对比表格与综述"""

    def __init__(self):
        super().__init__(name="Compare", use_fast_llm=False)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        对多篇论文生成对比分析

        state 需要包含:
        - papers_to_compare: list[dict]，每项含 {title, summary}
        """
        papers = state.get("papers_to_compare", [])
        if len(papers) < 2:
            return {"comparison": "请至少选择两篇论文进行对比分析。"}

        # 拼接每篇论文的摘要内容
        blocks = []
        for i, paper in enumerate(papers, 1):
            title = str(paper.get("title", f"论文{i}"))[:200]
            summary = str(paper.get("summary", "")).strip()
            if not summary:
                continue
            blocks.append(f"### 论文 {i}：{title}\n{summary[:3000]}")

        if len(blocks) < 2:
            return {"comparison": "选中的论文缺少摘要，无法对比，请先查看论文生成摘要。"}

        papers_text = "\n\n".join(blocks)

        system_prompt = get_prompt_by_name("compare.system")
        task_prompt = (
            get_prompt_by_name("compare.task")
            .replace("{count}", str(len(blocks)))
            .replace("{papers}", papers_text)
        )

        comparison = await self.invoke_llm(task_prompt, system=system_prompt)

        return {"comparison": comparison}
