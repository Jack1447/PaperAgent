"""推荐 Agent —— 基于用户记忆文档给出个性化研究建议。

两步：
  refine_memory: 读「旧记忆 + 行为信号」→ 提炼重写出用户兴趣档案；
  recommend:     读兴趣档案 → 产出研究方向 / 检索关键词 / 阅读建议。
"""
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent


class RecommendAgent(BaseAgent):
    """用户兴趣记忆提炼与个性化推荐 Agent。"""

    def __init__(self):
        super().__init__(name="Recommend", use_fast_llm=False)

    async def refine_memory(self, signals: str, old_memory: str) -> str:
        system = get_prompt_by_name("memory.refine_system")
        task = (
            get_prompt_by_name("memory.refine_task")
            .replace("{old_memory}", old_memory or "(暂无)")
            .replace("{signals}", signals or "(暂无)")
        )
        return await self.invoke_llm(task, system=system)

    async def recommend(self, memory: str) -> str:
        system = get_prompt_by_name("memory.recommend_system")
        task = get_prompt_by_name("memory.recommend_task").replace("{memory}", memory or "(暂无)")
        return await self.invoke_llm(task, system=system)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """state: {signals, old_memory}。先提炼记忆，再生成推荐。"""
        signals = state.get("signals", "")
        old_memory = state.get("old_memory", "")

        memory = await self.refine_memory(signals, old_memory)
        recommendation = await self.recommend(memory)
        return {"memory": memory, "recommendation": recommendation}
