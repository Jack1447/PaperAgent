"""
LiteLLM 统一 LLM 接口封装
支持 OpenAI / Claude / Gemini / DeepSeek / 通义千问 / Ollama 等 100+ 模型
"""
import logging
from typing import AsyncGenerator, Optional

import litellm
from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential

# Silence 'Give Feedback' banners on API errors
litellm.set_verbose = False

from config.settings import get_llm_config, get_retry_config, get_embedding_config
from src.llm.json_utils import extract_json_value

logger = logging.getLogger("paperagent.llm")


class LLMProvider:
    """LiteLLM 封装，支持流式和非流式调用"""

    def __init__(self, is_fast: bool = False):
        config = get_llm_config(is_fast)
        self.model: str = config["model"]
        self.api_key: str = config["api_key"]
        self.base_url: Optional[str] = config["base_url"]
        self.temperature: float = config["temperature"]
        self.max_tokens: int = config["max_tokens"]
        self.timeout: int = config["timeout"]

        retry_cfg = get_retry_config()
        self.max_retries = retry_cfg["max_attempts"]
        self.retry_min_wait = retry_cfg["min_wait"]
        self.retry_max_wait = retry_cfg["max_wait"]

    def _build_kwargs(self, **overrides) -> dict:
        kwargs = {
            "model": self.model,
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }
        # 只传非空的 base_url 给 LiteLLM（Ollama / 自定义 API 需要）
        if self.base_url:
            kwargs["api_base"] = self.base_url
        kwargs.update(overrides)
        return kwargs

    async def _acompletion_with_retry(self, **kwargs):
        last_error = None
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=1,
                min=self.retry_min_wait,
                max=self.retry_max_wait,
            ),
            reraise=True,
        ):
            with attempt:
                try:
                    return await litellm.acompletion(**kwargs)
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "LLM call failed (attempt %d/%d): model=%s error=%s",
                        attempt.retry_state.attempt_number if attempt.retry_state else 1,
                        self.max_retries,
                        self.model,
                        str(e)[:300],
                    )
                    raise
        # Should not reach here due to reraise=True, but just in case
        if last_error:
            raise last_error

    async def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        非流式调用 LLM，返回完整回复文本

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            system: 系统提示词（可选）
        """
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        call_kwargs = self._build_kwargs(**kwargs)
        response = await self._acompletion_with_retry(
            messages=full_messages,
            **call_kwargs,
        )
        return response.choices[0].message.content

    async def chat_stream(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        流式调用 LLM，逐 token 返回

        Args:
            messages: 对话消息列表
            system: 系统提示词（可选）
        """
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        call_kwargs = self._build_kwargs(stream=True, **kwargs)
        response = await litellm.acompletion(
            messages=full_messages,
            **call_kwargs,
        )
        async for chunk in response:
            if chunk.choices[0].delta.content is not None:
                yield chunk.choices[0].delta.content

    async def chat_json(
        self,
        messages: list[dict],
        system: Optional[str] = None,
    ) -> dict:
        """
        调用 LLM 并解析 JSON 输出

        Args:
            messages: 对话消息列表
            system: 系统提示词（可选）
        """
        # 在系统提示中加入 JSON 输出要求
        json_hint = "\n请以纯 JSON 格式输出，不要包含 markdown 代码块标记。"
        full_system = (system or "") + json_hint

        text = await self.chat(messages, system=full_system)
        return extract_json_value(text)


class EmbeddingProvider:
    """LiteLLM embedding 封装，批量取向量，带重试。

    复用主 LLM 的 Key/BaseURL（可由 EMBEDDING_* 覆盖），默认模型 bge-m3。
    """

    def __init__(self):
        config = get_embedding_config()
        self.model: str = config["model"]
        self.api_key: str = config["api_key"]
        self.base_url: Optional[str] = config["base_url"]

        retry_cfg = get_retry_config()
        self.max_retries = retry_cfg["max_attempts"]
        self.retry_min_wait = retry_cfg["min_wait"]
        self.retry_max_wait = retry_cfg["max_wait"]

    def _build_kwargs(self) -> dict:
        # 显式指定 openai 兼容 provider，让 LiteLLM 把原始 model 名（如
        # BAAI/bge-m3）原样发给 302.ai，避免它把 "BAAI/" 误当作 provider 前缀。
        kwargs = {
            "model": self.model,
            "api_key": self.api_key,
            "custom_llm_provider": "openai",
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url
        return kwargs

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量取 embedding，返回与输入等长的向量列表。"""
        if not texts:
            return []

        async def _call():
            return await litellm.aembedding(input=texts, **self._build_kwargs())

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(
                multiplier=1,
                min=self.retry_min_wait,
                max=self.retry_max_wait,
            ),
            reraise=True,
        ):
            with attempt:
                try:
                    response = await _call()
                except Exception as e:
                    logger.warning(
                        "Embedding call failed (attempt %d/%d): model=%s error=%s",
                        attempt.retry_state.attempt_number if attempt.retry_state else 1,
                        self.max_retries,
                        self.model,
                        str(e)[:300],
                    )
                    raise
        # litellm 返回 {"data": [{"embedding": [...]}, ...]}
        data = response["data"] if isinstance(response, dict) else response.data
        return [item["embedding"] for item in data]

    async def embed_one(self, text: str) -> list[float]:
        result = await self.embed([text])
        return result[0] if result else []
