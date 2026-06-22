"""用户级长期记忆模块。

负责：
1. 从 SQLite 搜索历史 + 会话状态（AppState）采集用户行为信号；
2. 读写持久化的记忆文档 data/memory.md（原子写）。

记忆文档本身的「提炼重写」由 RecommendAgent 调用 LLM 完成，本模块只负责
信号采集与文档存取，不直接调用大模型。
"""
from __future__ import annotations

import os
from typing import Any


def _memory_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "memory.md",
    )


class UserMemory:
    """用户记忆文档的存取与行为信号采集。"""

    def __init__(self, sqlite: Any | None = None):
        self._sqlite = sqlite
        self._path = _memory_path()

    @property
    def sqlite(self) -> Any:
        if self._sqlite is None:
            from src.memory.sqlite_store import SQLiteStore

            self._sqlite = SQLiteStore()
        return self._sqlite

    # ── 文档存取 ──

    def read_memory(self) -> str:
        if not os.path.exists(self._path):
            return ""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def write_memory(self, content: str) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        tmp_path = self._path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, self._path)  # atomic

    # ── 信号采集 ──

    def collect_signals(self, state: Any, max_searches: int = 20) -> str:
        """把用户的搜索记录、对话记录、已读论文整理成一段文本，供 LLM 提炼。

        state 为鸭子类型对象（AppState），通过 getattr 读取，避免对 web 层的依赖。
        """
        parts: list[str] = []

        # 1. 搜索记录（来自 SQLite，跨会话）
        try:
            searches = self.sqlite.get_recent_searches(limit=max_searches)
        except Exception:
            searches = []
        if searches:
            lines = []
            for s in searches:
                q = str(s.get("query", "")).strip()
                if q:
                    lines.append(f"- {q}（{int(s.get('paper_count', 0) or 0)} 篇）")
            if lines:
                parts.append("## 搜索记录\n" + "\n".join(lines))

        # 当前会话的查询与子主题
        query = getattr(state, "query", "")
        subtopics = getattr(state, "subtopics", []) or []
        if subtopics:
            names = [str(t.get("name", "")).strip() for t in subtopics if t.get("name")]
            if names:
                parts.append(
                    f"## 当前主题\n{query}\n子方向：" + "、".join(names)
                )

        # 2. 已读 / 已总结的论文
        papers = getattr(state, "papers", []) or []
        summaries = getattr(state, "summaries", {}) or {}
        reviews = getattr(state, "review_by_paper", {}) or {}
        from src.domain.models import paper_uid

        read_lines = []
        for p in papers:
            uid = paper_uid(p)
            if uid in summaries or uid in reviews:
                title = getattr(p, "title", "") or uid
                tags = []
                if uid in summaries:
                    tags.append("已总结")
                if uid in reviews:
                    tags.append("已评审")
                read_lines.append(f"- {title}（{'/'.join(tags)}）")
        if read_lines:
            parts.append("## 已读论文\n" + "\n".join(read_lines))

        # 3. 对话提问（用户关注点）
        chat_by_paper = getattr(state, "chat_by_paper", {}) or {}
        q_lines = []
        for uid, msgs in chat_by_paper.items():
            for m in msgs:
                if m.get("role") == "user":
                    text = str(m.get("content", "")).strip()
                    if text:
                        q_lines.append(f"- {text[:120]}")
        if q_lines:
            parts.append("## 用户提问\n" + "\n".join(q_lines[:30]))

        return "\n\n".join(parts).strip()
