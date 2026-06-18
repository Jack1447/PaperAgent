"""
arXiv API 客户端
提供论文搜索和 PDF 下载功能
"""
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional

import requests

from config.settings import get_search_config


@dataclass
class Paper:
    """论文数据模型"""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    arxiv_id: str = ""
    abstract: str = ""
    url: str = ""
    pdf_url: str = ""
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    citations: int = 0


class ArxivClient:
    """
    arXiv API 客户端

    使用 arXiv 官方 API (https://info.arxiv.org/help/api/)
    无需 API Key，免费使用
    限制: 每 3 秒一次请求
    """

    BASE_URL = "http://export.arxiv.org/api/query"

    def __init__(self):
        config = get_search_config()["arxiv"]
        self.max_results = config["max_results_per_keyword"]
        self.sort_by = config["sort_by"]
        self.rate_limit = config.get("rate_limit_seconds", 3)

        self._last_request_time = 0.0

    def _rate_limit(self):
        """请求限频保护"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
    ) -> list[Paper]:
        """
        搜索 arXiv 论文（多策略：先标题精准匹配，再全字段回退）

        Args:
            query: 搜索关键词（英文）
            max_results: 最大返回数量（默认使用配置值）

        Returns:
            论文列表
        """
        max_results = max_results or self.max_results

        # 策略1: 标题搜索 (ti:) — 更精准，优先使用
        papers = self._do_search(f"ti:{query}", max_results)
        # 策略2: 如果标题搜索不足，回退到全字段搜索 (all:)
        if len(papers) < max(max_results // 2, 3):
            fallback = self._do_search(f"all:{query}", max_results)
            existing_ids = {p.arxiv_id for p in papers}
            for p in fallback:
                if p.arxiv_id not in existing_ids:
                    papers.append(p)
                    existing_ids.add(p.arxiv_id)
                    if len(papers) >= max_results:
                        break
        return papers

    def _do_search(self, search_query: str, max_results: int) -> list[Paper]:
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": self.sort_by,
            "sortOrder": "descending",
        }

        self._rate_limit()

        try:
            response = requests.get(
                self.BASE_URL,
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            return self._parse_response(response.text)
        except requests.RequestException as e:
            print(f"[ArxivClient] 搜索失败: {e}")
            return []

    def get_paper_by_id(self, arxiv_id: str) -> Optional[Paper]:
        """根据 arXiv ID 获取单篇论文"""
        clean_id = self._clean_id(arxiv_id)
        params = {
            "id_list": clean_id,
            "max_results": 1,
        }
        self._rate_limit()

        try:
            response = requests.get(self.BASE_URL, params=params, timeout=30)
            response.raise_for_status()
            papers = self._parse_response(response.text)
            return papers[0] if papers else None
        except requests.RequestException as e:
            print(f"[ArxivClient] 获取论文失败 {arxiv_id}: {e}")
            return None

    def download_pdf(self, paper: Paper, save_path: str) -> bool:
        """
        下载论文 PDF

        Returns:
            是否下载成功
        """
        self._rate_limit()

        try:
            response = requests.get(paper.pdf_url, timeout=60)
            response.raise_for_status()
            with open(save_path, "wb") as f:
                f.write(response.content)
            return True
        except requests.RequestException as e:
            print(f"[ArxivClient] PDF下载失败 {paper.arxiv_id}: {e}")
            return False

    def _clean_id(self, arxiv_id: str) -> str:
        """清理 arXiv ID"""
        return (arxiv_id
            .replace("https://arxiv.org/abs/", "")
            .replace("https://arxiv.org/pdf/", "")
            .replace(".pdf", "")
            .strip()
        )

    def find_by_title(self, title: str) -> Optional[Paper]:
        """根据论文标题查找 arXiv 版本，多策略逐步放宽匹配条件。

        核心改进：使用 ti:word1+AND+word2 组合词搜索代替 ti:"phrase" 严格短语搜索，
        避免因标题中个别词差异（大小写、标点、多余内容）导致整条匹配失败。
        """
        if not title or not title.strip():
            return None

        # Clean: remove punctuation, collapse whitespace
        clean_full = re.sub(r"[^a-zA-Z0-9\s]", " ", title)
        clean_full = re.sub(r"\s+", " ", clean_full).strip()[:300]
        # Significant words (skip short stopwords like "a", "an", "to", "of", "in", "on", "is")
        skip_words = {"a", "an", "the", "to", "of", "in", "on", "is", "at", "by", "for", "and", "or", "with", "from"}
        sig_words = [w for w in clean_full.split() if len(w) > 2 or w.lower() not in skip_words]
        if not sig_words:
            sig_words = [w for w in clean_full.split() if len(w) > 1]

        # Build AND-based queries (much more robust than quoted phrase search)
        and_all = "+AND+".join(sig_words[:12])
        and_8 = "+AND+".join(sig_words[:8])
        and_5 = "+AND+".join(sig_words[:5])
        phrase_short = " ".join(sig_words[:8])

        queries = [
            # Strategy 1: ti with AND of up to 12 significant words (most precise)
            f"ti:{and_all}",
            # Strategy 2: ti with AND of first 8 words
            f"ti:{and_8}",
            # Strategy 3: all fields, AND of up to 12 words
            f"all:{and_all}",
            # Strategy 4: all fields, AND of first 8 words
            f"all:{and_8}",
            # Strategy 5: all fields, AND of first 5 words (loose)
            f"all:{and_5}",
            # Strategy 6: all fields, short phrase (last resort)
            f'all:"{phrase_short}"',
        ]

        for i, query in enumerate(queries):
            params = {
                "search_query": query,
                "start": 0,
                "max_results": 5,
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            self._rate_limit()
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=20)
                resp.raise_for_status()
                papers = self._parse_response(resp.text)
                if papers:
                    best = self._best_title_match(title, papers)
                    if best:
                        return best
            except requests.RequestException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status:
                    print(f"[ArxivClient] find_by_title strat {i+1} HTTP {status}: {e}")
                else:
                    print(f"[ArxivClient] find_by_title strat {i+1}: {e}")
                continue

        return None

    def _best_title_match(self, query_title: str, candidates: list[Paper]) -> Optional[Paper]:
        """Pick the best candidate by Jaccard token overlap."""
        def tokenize(s: str) -> set[str]:
            return set(re.findall(r"[a-z0-9]+", s.lower()))

        qt = tokenize(query_title)
        if not qt:
            return candidates[0] if candidates else None

        scored = []
        for p in candidates:
            ct = tokenize(p.title)
            if not ct:
                scored.append((0, p))
                continue
            intersection = qt & ct
            union = qt | ct
            sim = len(intersection) / len(union) if union else 0
            scored.append((sim, p))

        scored.sort(key=lambda x: -x[0])
        # Require at least 40% overlap to consider a match
        return scored[0][1] if scored and scored[0][0] >= 0.4 else None

    def _parse_response(self, xml_text: str) -> list[Paper]:
        """解析 arXiv API 返回的 XML"""
        import xml.etree.ElementTree as ET

        papers = []
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return papers

        for entry in root.findall("atom:entry", ns):
            try:
                paper = Paper()

                title_el = entry.find("atom:title", ns)
                paper.title = " ".join(title_el.text.split()) if title_el is not None and title_el.text else ""

                paper.authors = [
                    author.find("atom:name", ns).text
                    for author in entry.findall("atom:author", ns)
                    if author.find("atom:name", ns) is not None
                ]

                id_el = entry.find("atom:id", ns)
                if id_el is not None and id_el.text:
                    paper.arxiv_id = id_el.text.split("/abs/")[-1]

                summary_el = entry.find("atom:summary", ns)
                paper.abstract = " ".join(summary_el.text.split()) if summary_el is not None and summary_el.text else ""

                link_el = entry.find("atom:link[@title='pdf']", ns)
                if link_el is not None:
                    paper.pdf_url = link_el.attrib["href"]
                else:
                    paper.pdf_url = f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"

                paper.url = f"https://arxiv.org/abs/{paper.arxiv_id}"

                published_el = entry.find("atom:published", ns)
                paper.published = published_el.text[:10] if published_el is not None and published_el.text else ""

                updated_el = entry.find("atom:updated", ns)
                paper.updated = updated_el.text[:10] if updated_el is not None and updated_el.text else ""

                paper.categories = [
                    cat.attrib["term"]
                    for cat in entry.findall("atom:category", ns)
                ]

                comment_el = entry.find("arxiv:comment", ns)
                paper.comment = comment_el.text if comment_el is not None and comment_el.text else ""

                papers.append(paper)

            except Exception as e:
                print(f"[ArxivClient] 解析条目失败: {e}")
                continue

        return papers
