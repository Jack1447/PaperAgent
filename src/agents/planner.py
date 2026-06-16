"""
Planner Agent
将用户研究主题拆解为多个子研究方向
"""
from typing import Any

from config.settings import get_prompt_by_name
from src.agents.base import BaseAgent
from src.llm.json_utils import extract_json_value, normalize_planner_subtopics


class PlannerAgent(BaseAgent):
    """研究规划 Agent —— 将模糊主题拆解为可执行的子研究方向"""

    def __init__(self):
        super().__init__(name="Planner", use_fast_llm=True)

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        user_query = state.get("user_query", "")

        system_prompt = get_prompt_by_name("planner.system")
        task_prompt = get_prompt_by_name("planner.task").replace("{query}", user_query)

        raw = await self.invoke_llm(task_prompt, system=system_prompt)

        # 解析并归一化 JSON
        subtopics = self._parse_json(raw, fallback_query=user_query)

        return {
            "subtopics": subtopics,
            "plan_feedback": "",
        }

    def _parse_json(self, raw: str, fallback_query: str = "") -> list[dict]:
        """鲁棒的 JSON 解析"""
        try:
            value = extract_json_value(raw)
            subtopics = normalize_planner_subtopics(value, fallback_query=fallback_query)
            if subtopics:
                return subtopics
        except ValueError:
            pass

        # 降级：返回单主题
        query = fallback_query.strip() or raw.strip()
        return [{
            "name": "main topic",
            "description": query[:200],
            "keywords": [query[:100]]
        }]
