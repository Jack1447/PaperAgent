"""
配置加载器
从 .env 和 YAML 文件加载所有配置项
"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 加载 .env 文件
load_dotenv(PROJECT_ROOT / ".env")

# 加载 YAML 配置
def _load_yaml(filename: str) -> dict:
    path = PROJECT_ROOT / "config" / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

_llm_config = _load_yaml("llm.yaml")
_search_config = _load_yaml("search.yaml")
_prompts_config = _load_yaml("prompts.yaml")


# ========== LLM 配置 ==========

class LLMConfigError(Exception):
    """LLM 未配置或配置错误"""

def get_llm_config(is_fast: bool = False) -> dict:
    """获取 LLM 配置"""
    prefix = "FAST_" if is_fast else ""

    model = os.getenv(f"{prefix}LLM_MODEL")
    api_key = os.getenv(f"{prefix}LLM_API_KEY")
    base_url = os.getenv(f"{prefix}LLM_BASE_URL")

    if not model or not api_key:
        raise LLMConfigError(
            f"请在 .env 文件中配置 {prefix}LLM_MODEL 和 {prefix}LLM_API_KEY"
        )

    model_params = (
        _llm_config["fast_model"] if is_fast
        else _llm_config["main_model"]
    )

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url or None,
        "temperature": model_params["temperature"],
        "max_tokens": model_params["max_tokens"],
        "timeout": model_params["timeout"],
    }


def get_retry_config() -> dict:
    return _llm_config["retry"]


# ========== Embedding 配置 ==========

def get_embedding_config() -> dict:
    """获取 embedding 配置。

    默认复用主 LLM 的 API Key / Base URL，可通过 EMBEDDING_* 单独覆盖。
    """
    model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY")
    base_url = os.getenv("EMBEDDING_BASE_URL") or os.getenv("LLM_BASE_URL")

    if not api_key:
        raise LLMConfigError(
            "请在 .env 文件中配置 EMBEDDING_API_KEY 或 LLM_API_KEY（embedding 复用主 LLM Key）"
        )

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url or None,
    }


# ========== 搜索配置 ==========

def get_search_config() -> dict:
    return _search_config


# ========== Prompt 配置 ==========

def get_prompt(agent: str, key: str = "system") -> str:
    """获取指定 Agent 的 Prompt 模板"""
    return _prompts_config.get(agent, {}).get(key, "")


def get_prompt_by_name(name: str) -> str:
    """
    获取指定名称的 prompt，支持点号分隔的嵌套路径
    例如: "summarize.stage1" 或 "planner.task"
    """
    parts = name.split(".")
    prompt = _prompts_config
    for part in parts:
        prompt = prompt.get(part, {})
    return prompt if isinstance(prompt, str) else ""


# ========== 通用配置 ==========

def get_language() -> str:
    return os.getenv("LANGUAGE", "zh")
