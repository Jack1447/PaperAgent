"""
内存向量存储（纯 Python 实现，替代 ChromaDB）
论文摘要和全文 chunk 的语义检索

ChromaDB 在 Windows 上不可用（Rust binding 兼容性问题），
使用简单的 dict + TF-IDF 关键词匹配替代。

数据持久化到 data/chunks.json，重启不丢失。
"""
import json
import math
import os
import re
import threading
from collections import Counter
from typing import Optional


def _store_path() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "chunks.json",
    )


class _SimpleVectorStore:
    """Simple in-memory TF-IDF based text store with JSON persistence."""

    def __init__(self):
        self._docs: dict[str, str] = {}
        self._metas: dict[str, dict] = {}
        self._idf: dict[str, float] = {}
        self._dirty = True

    def _tokenize(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        cjk = re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]", text)
        return tokens + cjk

    def _compute_idf(self):
        n = len(self._docs)
        df: Counter = Counter()
        for text in self._docs.values():
            terms = set(self._tokenize(text))
            df.update(terms)
        self._idf = {}
        for term, count in df.items():
            self._idf[term] = math.log((1 + n) / (1 + count)) + 1
        self._dirty = False

    def _tfidf(self, text: str) -> Counter:
        terms = self._tokenize(text)
        if not terms:
            return Counter()
        tf = Counter(terms)
        max_freq = max(tf.values())
        result = Counter()
        for term, freq in tf.items():
            result[term] = (freq / max_freq) * self._idf.get(term, 1)
        return result

    def upsert(self, doc_id: str, text: str, metadata: Optional[dict] = None):
        self._docs[doc_id] = text
        self._metas[doc_id] = metadata or {}
        self._dirty = True

    def delete(self, doc_ids: list[str]):
        for did in doc_ids:
            self._docs.pop(did, None)
            self._metas.pop(did, None)
        self._dirty = True

    def get(self, doc_id: str) -> Optional[tuple[str, dict]]:
        text = self._docs.get(doc_id)
        if text is None:
            return None
        return text, self._metas.get(doc_id, {})

    def query(self, query_text: str, top_k: int = 5, where: Optional[dict] = None) -> list[dict]:
        if not self._docs:
            return []
        if self._dirty:
            self._compute_idf()
        q_vec = self._tfidf(query_text)
        if not q_vec:
            return []

        scored = []
        for doc_id, text in self._docs.items():
            meta = self._metas.get(doc_id, {})
            if where:
                skip = False
                for k, v in where.items():
                    if meta.get(k) != v:
                        skip = True
                        break
                if skip:
                    continue
            d_vec = self._tfidf(text)
            dot = sum(q_vec[t] * d_vec[t] for t in q_vec if t in d_vec)
            if dot > 0:
                scored.append((dot, doc_id, text, meta))

        scored.sort(key=lambda x: -x[0])
        result = []
        for i, (score, doc_id, text, meta) in enumerate(scored[:top_k]):
            result.append({
                "id": doc_id,
                "text": text,
                "metadata": meta,
                "distance": -score,
            })
        return result

    def to_dict(self) -> dict:
        return {
            "docs": self._docs,
            "metas": self._metas,
        }

    def from_dict(self, data: dict):
        self._docs = data.get("docs", {})
        self._metas = data.get("metas", {})
        self._dirty = True


class SimpleStore:
    """论文摘要 & 全文 chunk 内存存储（替代 ChromaDB）

    Singleton — all agents share the same in-memory store.
    Data persisted to data/chunks.json.
    """

    _instance: Optional["SimpleStore"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, persist_dir: str = ""):
        if self._initialized:
            return
        self._initialized = True
        self._persist_path = _store_path()
        self._save_lock = threading.Lock()
        self.summaries = _SimpleVectorStore()
        self.chunks = _SimpleVectorStore()
        self._load()

    def _load(self):
        if not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.summaries.from_dict(data.get("summaries", {}))
            self.chunks.from_dict(data.get("chunks", {}))
        except Exception:
            pass  # corrupted file, start fresh

    def _save(self):
        os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
        data = {
            "summaries": self.summaries.to_dict(),
            "chunks": self.chunks.to_dict(),
        }
        with self._save_lock:
            try:
                with open(self._persist_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except OSError:
                pass  # skip save on write error, data lives in memory

    def add_summary(self, arxiv_id: str, title: str, summary_text: str,
                    metadata: Optional[dict] = None):
        meta = metadata or {}
        meta["arxiv_id"] = arxiv_id
        meta["title"] = title
        self.summaries.upsert(arxiv_id, summary_text, meta)
        self._save()

    def search_summaries(self, query: str, top_k: int = 5) -> list[dict]:
        return self.summaries.query(query, top_k)

    def get_summary(self, arxiv_id: str) -> Optional[str]:
        result = self.summaries.get(arxiv_id)
        return result[0] if result else None

    def add_chunks(self, arxiv_id: str, chunks: list[dict]):
        if not chunks:
            return
        ids = [f"{arxiv_id}_{c['chunk_id']}" for c in chunks]
        old_ids = [k for k in self.chunks._docs.keys() if k.startswith(f"{arxiv_id}_")]
        if old_ids:
            self.chunks.delete(old_ids)
        for i, chunk in enumerate(chunks):
            meta = {
                "arxiv_id": arxiv_id,
                "chunk_id": chunk.get("chunk_id", i),
                "section": chunk.get("section", "unknown"),
            }
            self.chunks.upsert(ids[i], chunk["text"], meta)
        self._save()

    def search_chunks(self, arxiv_id: str, query: str, top_k: int = 5) -> list[dict]:
        return self.chunks.query(query, top_k, where={"arxiv_id": arxiv_id})

    def paper_exists(self, arxiv_id: str) -> bool:
        return self.summaries.get(arxiv_id) is not None


ChromaStore = SimpleStore
