"""
Agent 基类
所有 Agent 继承此基类，获得 LLM 调用和状态管理能力
"""
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.llm.provider import LLMProvider


class BaseAgent(ABC):
    """Agent 基类"""

    def __init__(
        self,
        name: str,
        use_fast_llm: bool = False,
    ):
        from src.llm.provider import LLMProvider

        self.name = name
        self.llm = LLMProvider(is_fast=use_fast_llm)

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        执行 Agent 主逻辑

        Args:
            state: LangGraph 全局状态

        Returns:
            更新后的状态字段 (部分更新)
        """
        ...

    async def invoke_llm(
        self,
        prompt: str,
        system: str = "",
    ) -> str:
        """非流式调用 LLM"""
        return await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )

    async def invoke_llm_json(
        self,
        prompt: str,
        system: str = "",
    ) -> dict:
        """调用 LLM 并解析 JSON 返回"""
        return await self.llm.chat_json(
            messages=[{"role": "user", "content": prompt}],
            system=system,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', model='{self.llm.model}')>"
