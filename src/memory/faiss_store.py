"""基于 FAISS 的论文 chunk 语义检索存储。

设计：
- 每篇论文（含 `{arxiv_id}_detail`）一个独立的小 FAISS 索引，
  持久化到 data/faiss/{safe_id}.index + 平行的 {safe_id}.meta.json。
- 用 IndexFlatIP（内积）+ 向量 L2 归一化 = cosine 相似度。
- chunk 入库时批量调 embedding；检索时对 query 单独取向量。
- embedding 调用失败/未配置时不抛异常，add 跳过、search 返回空，
  交由上层（ReadingAgent / ReviewAgent）已有的 summary/abstract fallback 接管。
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np


def _faiss_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "faiss",
    )


def _safe_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def _run_async(coro):
    """在独立线程里跑协程，无论调用处有无运行中的事件循环都安全。"""
    import asyncio

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro)).result()


class FaissStore:
    """每篇论文一个 FAISS 索引的 chunk 语义检索存储（单例）。"""

    _instance: Optional["FaissStore"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._dir = _faiss_dir()
        self._lock = threading.Lock()
        os.makedirs(self._dir, exist_ok=True)

    # ── 路径 ──

    def _index_path(self, arxiv_id: str) -> str:
        return os.path.join(self._dir, f"{_safe_id(arxiv_id)}.index")

    def _meta_path(self, arxiv_id: str) -> str:
        return os.path.join(self._dir, f"{_safe_id(arxiv_id)}.meta.json")

    # ── embedding ──

    def _embed(self, texts: list[str]) -> Optional[np.ndarray]:
        """批量取 embedding，返回归一化后的矩阵；失败返回 None。"""
        if not texts:
            return None
        try:
            from src.llm.provider import EmbeddingProvider

            provider = EmbeddingProvider()
            vectors = _run_async(provider.embed(texts))
        except Exception as e:  # 未配置 / 报错 / 超时
            print(f"[FaissStore] embedding 调用失败，跳过向量化: {e}")
            return None
        if not vectors:
            return None
        mat = np.asarray(vectors, dtype="float32")
        # L2 归一化 → 内积即 cosine
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return mat / norms

    # ── 写入 ──

    def add_chunks(self, arxiv_id: str, chunks: list[dict]) -> None:
        if not chunks:
            return
        texts, metas = [], []
        for i, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            if not text or not text.strip():
                continue
            texts.append(text)
            metas.append({
                "arxiv_id": arxiv_id,
                "chunk_id": chunk.get("chunk_id", i),
                "section": chunk.get("section", "unknown"),
                "text": text,
            })
        if not texts:
            return

        mat = self._embed(texts)
        if mat is None:
            return  # embedding 不可用，放弃本篇向量化（上层有 fallback）

        import faiss

        index = faiss.IndexFlatIP(mat.shape[1])
        index.add(mat)

        with self._lock:
            os.makedirs(self._dir, exist_ok=True)
            # 用 serialize + Python IO 写入，规避 faiss C 文件 IO 不支持中文路径的问题
            index_bytes = faiss.serialize_index(index).tobytes()
            with open(self._index_path(arxiv_id), "wb") as f:
                f.write(index_bytes)
            with open(self._meta_path(arxiv_id), "w", encoding="utf-8") as f:
                json.dump(metas, f, ensure_ascii=False)

    # ── 检索 ──

    def search_chunks(self, arxiv_id: str, query: str, top_k: int = 5) -> list[dict]:
        index_path = self._index_path(arxiv_id)
        meta_path = self._meta_path(arxiv_id)
        if not (os.path.exists(index_path) and os.path.exists(meta_path)):
            return []

        q_mat = self._embed([query])
        if q_mat is None:
            return []

        import faiss

        try:
            with open(index_path, "rb") as f:
                index_bytes = f.read()
            index = faiss.deserialize_index(np.frombuffer(index_bytes, dtype="uint8"))
            with open(meta_path, "r", encoding="utf-8") as f:
                metas = json.load(f)
        except Exception as e:
            print(f"[FaissStore] 读取索引失败: {e}")
            return []

        k = min(top_k, index.ntotal)
        if k <= 0:
            return []
        scores, ids = index.search(q_mat, k)

        results = []
        for score, idx in zip(scores[0], ids[0]):
            if idx < 0 or idx >= len(metas):
                continue
            meta = metas[idx]
            results.append({
                "id": f"{meta['arxiv_id']}_{meta['chunk_id']}",
                "text": meta["text"],
                "metadata": {
                    "arxiv_id": meta["arxiv_id"],
                    "chunk_id": meta["chunk_id"],
                    "section": meta["section"],
                },
                "distance": float(-score),  # 与原接口一致：越小越相关
            })
        return results

    def paper_exists(self, arxiv_id: str) -> bool:
        return os.path.exists(self._index_path(arxiv_id))
