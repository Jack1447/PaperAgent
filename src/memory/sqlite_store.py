"""
SQLite 结构化存储
搜索历史、用户偏好、论文收藏
"""
import json
import os
import sqlite3
import time
from typing import Optional


class SQLiteStore:
    """轻量级结构化存储"""

    def __init__(self, db_path: str = "data/paperagent.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self):
        with self._get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS search_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    query TEXT NOT NULL,
                    subtopics TEXT,          -- JSON: Planner 子主题
                    paper_count INTEGER DEFAULT 0,
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );

                CREATE TABLE IF NOT EXISTS papers (
                    arxiv_id TEXT PRIMARY KEY,
                    title TEXT,
                    authors TEXT,             -- JSON array
                    abstract TEXT,
                    url TEXT,
                    published TEXT,
                    citations INTEGER DEFAULT 0,
                    summary TEXT,             -- Summarize Agent 输出的结构化摘要
                    created_at REAL DEFAULT (strftime('%s', 'now'))
                );

                CREATE TABLE IF NOT EXISTS favorites (
                    arxiv_id TEXT PRIMARY KEY,
                    added_at REAL DEFAULT (strftime('%s', 'now'))
                );

                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    # ========== 搜索历史 ==========

    def save_search(
        self,
        query: str,
        subtopics: list[dict],
        paper_count: int,
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO search_history (query, subtopics, paper_count) VALUES (?, ?, ?)",
                (query, json.dumps(subtopics, ensure_ascii=False), paper_count),
            )
            return cursor.lastrowid

    def get_recent_searches(self, limit: int = 10) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM search_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ========== 论文 ==========

    def save_paper(
        self,
        arxiv_id: str,
        title: str = "",
        authors: list[str] | None = None,
        abstract: str = "",
        url: str = "",
        published: str = "",
        citations: int = 0,
        summary: str = "",
    ):
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO papers
                   (arxiv_id, title, authors, abstract, url, published, citations, summary)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    arxiv_id, title,
                    json.dumps(authors or [], ensure_ascii=False),
                    abstract, url, published, citations, summary,
                ),
            )

    def get_paper(self, arxiv_id: str) -> Optional[dict]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
        return dict(row) if row else None

    # ========== 收藏 ==========

    def add_favorite(self, arxiv_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO favorites (arxiv_id) VALUES (?)",
                (arxiv_id,),
            )

    def remove_favorite(self, arxiv_id: str):
        with self._get_conn() as conn:
            conn.execute(
                "DELETE FROM favorites WHERE arxiv_id = ?", (arxiv_id,)
            )

    def get_favorites(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT p.* FROM papers p
                   JOIN favorites f ON p.arxiv_id = f.arxiv_id
                   ORDER BY f.added_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def is_favorite(self, arxiv_id: str) -> bool:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM favorites WHERE arxiv_id = ?", (arxiv_id,)
            ).fetchone()
        return row is not None

    # ========== 偏好 ==========

    def set_preference(self, key: str, value: str):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_preferences (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_preference(self, key: str, default: str = "") -> str:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM user_preferences WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default
