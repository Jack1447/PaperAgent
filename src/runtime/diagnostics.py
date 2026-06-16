"""Runtime diagnostics for configuration, dependencies, and local storage."""
from __future__ import annotations

import importlib.util
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from config.settings import PROJECT_ROOT


@dataclass(frozen=True)
class DiagnosticItem:
    name: str
    ok: bool
    message: str
    required: bool = True


@dataclass
class RuntimeDiagnostics:
    items: list[DiagnosticItem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items if item.required)

    @property
    def warnings(self) -> list[DiagnosticItem]:
        return [item for item in self.items if not item.ok and not item.required]

    @property
    def failures(self) -> list[DiagnosticItem]:
        return [item for item in self.items if not item.ok and item.required]


def run_diagnostics() -> RuntimeDiagnostics:
    items: list[DiagnosticItem] = []
    items.append(check_python_runtime())
    items.extend(check_llm_env())
    items.extend(check_dependencies())
    items.extend(check_storage())
    return RuntimeDiagnostics(items)


def check_python_runtime() -> DiagnosticItem:
    env_name = os.getenv("CONDA_DEFAULT_ENV", "")
    suffix = f" · conda={env_name}" if env_name else ""
    return DiagnosticItem(
        name="Python",
        ok=True,
        message=f"{sys.executable}{suffix}",
        required=False,
    )


def check_llm_env() -> list[DiagnosticItem]:
    items = []
    items.append(_check_env_pair("主模型", "LLM_MODEL", "LLM_API_KEY", required=True))
    items.append(_check_env_pair("快速模型", "FAST_LLM_MODEL", "FAST_LLM_API_KEY", required=True))

    if not os.getenv("SCHOLAR_API_KEY"):
        items.append(DiagnosticItem(
            name="SerpAPI Scholar",
            ok=True,
            message="未配置 Scholar Key，将仅使用 arXiv。",
            required=False,
        ))
    return items


def check_dependencies() -> list[DiagnosticItem]:
    specs = [
        ("streamlit", "streamlit", True),
        ("litellm", "litellm", True),
        ("langgraph", "langgraph", False),
        ("chromadb", "chromadb", True),
        ("PyMuPDF", "fitz", True),
        ("langchain text splitters", "langchain_text_splitters", True),
        ("requests", "requests", True),
        ("yaml", "yaml", True),
        ("dotenv", "dotenv", True),
    ]
    return [
        DiagnosticItem(
            name=f"依赖: {label}",
            ok=importlib.util.find_spec(module) is not None,
            message="已安装" if importlib.util.find_spec(module) is not None else f"缺少 Python 包 `{module}`",
            required=required,
        )
        for label, module, required in specs
    ]


def check_storage() -> list[DiagnosticItem]:
    data_dir = PROJECT_ROOT / "data"
    chroma_dir = data_dir / "chroma_db"
    pdf_dir = data_dir / "pdf_cache"
    return [
        _check_writable_dir("数据目录", data_dir, required=True),
        _check_writable_dir("ChromaDB 目录", chroma_dir, required=True),
        _check_writable_dir("PDF 缓存目录", pdf_dir, required=True),
    ]


def _check_env_pair(
    name: str,
    model_key: str,
    api_key: str,
    required: bool,
) -> DiagnosticItem:
    model = os.getenv(model_key, "").strip()
    key = os.getenv(api_key, "").strip()
    ok = bool(model and key)
    if ok:
        message = f"{model_key}={model}"
    else:
        missing = [k for k, value in [(model_key, model), (api_key, key)] if not value]
        message = "缺少 " + ", ".join(missing)
    return DiagnosticItem(name=name, ok=ok, message=message, required=required)


def _check_writable_dir(name: str, path: Path, required: bool) -> DiagnosticItem:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / "write_test.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.read_text(encoding="utf-8")
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        return DiagnosticItem(name=name, ok=True, message=str(path), required=required)
    except Exception as exc:
        return DiagnosticItem(
            name=name,
            ok=False,
            message=f"{path}: {exc}",
            required=required,
        )
