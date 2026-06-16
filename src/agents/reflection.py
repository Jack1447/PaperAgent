"""
Reflection Agent
质量评审 —— 对平面、搜索、摘要三阶段的输出进行评审
"""
import json
from typing import Any

from config.settings import get_prompt_by_name, get_search_config
from src.agents.base import BaseAgent


class ReflectionAgent(BaseAgent):
    """
    反思 Agent
    职责:
    1. 评审规划合理性 (plan_check)
    2. 评审搜索结果质量 (search_check)
    3. 评审摘要完整性 (summary_check)
    """

    def __init__(self):
        super().__init__(name="Reflection", use_fast_llm=True)

    def _is_pass(self, raw: str) -> bool:
        """Return True only for explicit PASS responses."""

        text = raw.strip().upper()
        first_line = text.splitlines()[0].strip() if text else ""
        return text == "PASS" or first_line == "PASS"

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """主入口，根据当前状态自动选择评审类型"""
        # 根据状态判断需要评审什么
        if state.get("subtopics") and not state.get("plan_quality_pass"):
            return await self._check_plan(state)
        elif state.get("papers") and not state.get("search_quality_pass"):
            return await self._check_search(state)
        elif state.get("summaries"):
            return await self._check_summary(state)
        else:
            # 默认放行
            return {"search_quality_pass": True, "search_retry_count": 0}

    async def _check_plan(self, state: dict[str, Any]) -> dict[str, Any]:
        """评审 Plan 的合理性"""
        query = state.get("user_query", "")
        subtopics = state.get("subtopics", [])

        # 快速规则检查：子主题数量
        if not subtopics:
            return {
                "plan_quality_pass": False,
                "plan_feedback": "规划失败，无子主题生成。请重新规划。",
            }

        # LLM 评审
        system_prompt = get_prompt_by_name("reflection.system")
        subtopics_str = json.dumps(subtopics, ensure_ascii=False, indent=2)

        task_prompt = (
            get_prompt_by_name("reflection.plan_check")
            .replace("{query}", query)
            .replace("{subtopics}", subtopics_str)
        )

        raw = await self.invoke_llm(task_prompt, system=system_prompt)

        if self._is_pass(raw):
            return {"plan_quality_pass": True, "plan_feedback": ""}
        else:
            return {"plan_quality_pass": False, "plan_feedback": raw}

    async def _check_search(self, state: dict[str, Any]) -> dict[str, Any]:
        """评审搜索结果的论文质量"""
        papers = state.get("papers", [])
        query = state.get("user_query", "")
        retry_count = state.get("search_retry_count", 0)
        config = get_search_config()

        # 快速规则检查
        if len(papers) < config["min_relevant_papers"]:
            if retry_count < config["max_search_retries"]:
                return {
                    "search_quality_pass": False,
                    "search_retry_count": retry_count + 1,
                    "reflection_feedback": "论文数量不足，需要扩大搜索范围。",
                }
            else:
                return {
                    "search_quality_pass": True,
                    "search_retry_count": retry_count,
                }

        # LLM 评审
        # 生成论文摘要列表供评审
        paper_list = "\n".join(
            f"{i+1}. {p.title} ({p.published}) - {p.citations} citations"
            for i, p in enumerate(papers[:20])
        )

        task_prompt = (
            get_prompt_by_name("reflection.search_check")
            .replace("{query}", query)
            .replace("{count}", str(len(papers)))
            .replace("{paper_list}", paper_list)
        )

        raw = await self.invoke_llm(
            task_prompt,
            system=get_prompt_by_name("reflection.system"),
        )

        if self._is_pass(raw):
            return {
                "search_quality_pass": True,
                "search_retry_count": retry_count,
            }

        # 不通过：提取改进建议
        if retry_count < config["max_search_retries"]:
            return {
                "search_quality_pass": False,
                "search_retry_count": retry_count + 1,
                "reflection_feedback": raw,
            }
        else:
            return {
                "search_quality_pass": True,
                "search_retry_count": retry_count,
                "reflection_feedback": raw,
            }

    async def _check_summary(self, state: dict[str, Any]) -> dict[str, Any]:
        """评审摘要完整性"""
        summaries = state.get("summaries", {})
        if not summaries:
            return {"summary_quality_pass": True}

        # 抽样检查一篇
        sample_key = list(summaries.keys())[0]
        sample = summaries[sample_key]

        task_prompt = (
            get_prompt_by_name("reflection.summary_check")
            .replace("{title}", sample_key)
            .replace("{summary}", str(sample)[:2000])
        )

        raw = await self.invoke_llm(
            task_prompt,
            system=get_prompt_by_name("reflection.system"),
        )

        return {
            "summary_quality_pass": self._is_pass(raw),
            "reflection_feedback": "" if self._is_pass(raw) else raw,
        }
