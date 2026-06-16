"""
SerpAPI Scholar 客户端 (通过 302.ai / SerpAPI 代理)
"""
import re
import time
from typing import Optional

import requests

from config.settings import get_search_config
from src.tools.arxiv_client import Paper


class ScholarClient:
    """SerpAPI google_scholar 引擎客户端。

    通过 302.ai 或其他 SerpAPI 代理调用 Google Scholar。
    API 参考: https://serpapi.com/google-scholar-api
    """

    def __init__(self, api_key: str = "", base_url: str = "", arxiv_client=None):
        config = get_search_config().get("scholar", {})
        self.max_results = config.get("max_results_per_keyword", 10)
        self.api_key = api_key
        self.base_url = base_url or config.get("base_url", "https://serpapi.com/search")
        self._last_request_time = 0.0
        self.rate_limit = config.get("rate_limit_seconds", 2)
        self._arxiv_client = arxiv_client  # for reverse lookup

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        year_from: Optional[int] = None,
    ) -> list[Paper]:
        max_results = max_results or self.max_results
        self._rate_limit()

        params = {
            "engine": "google_scholar",
            "q": query,
            "num": min(max_results, 20),
            "hl": "en",
        }
        if self.api_key:
            params["api_key"] = self.api_key
        if year_from:
            params["as_ylo"] = year_from

        headers = {}
        if self.api_key and "302.ai" in self.base_url:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.get(
                self.base_url,
                params=params,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            return self._parse_search_results(response.json())
        except requests.RequestException as e:
            print(f"[Scholar] 搜索失败: {e}")
            return []

    def _parse_search_results(self, data: dict) -> list[Paper]:
        papers = []
        for item in data.get("organic_results", []):
            try:
                paper = Paper()
                paper.title = item.get("title", "")
                paper.url = item.get("link", "")
                paper.abstract = item.get("snippet", "")

                pub_info = item.get("publication_info", {})
                summary = pub_info.get("summary", "")
                if " - " in summary:
                    parts = summary.split(" - ", 1)
                    paper.authors = [
                        a.strip() for a in parts[0].split(",") if a.strip()
                    ]
                    rest = parts[1] if len(parts) > 1 else ""
                    year_match = re.search(r"\b(19|20)\d{2}\b", rest)
                    if year_match:
                        paper.published = year_match.group()

                link = paper.url or ""
                arxiv_match = re.search(r"arxiv\.org/abs/([\w.-]+)", link, re.IGNORECASE)
                if arxiv_match:
                    paper.arxiv_id = arxiv_match.group(1)
                    paper.pdf_url = f"https://arxiv.org/pdf/{paper.arxiv_id}.pdf"
                elif self._arxiv_client and paper.title:
                    # Try reverse lookup on arXiv by title
                    arxiv_paper = self._arxiv_client.find_by_title(paper.title)
                    if arxiv_paper and arxiv_paper.arxiv_id:
                        paper.arxiv_id = arxiv_paper.arxiv_id
                        paper.pdf_url = arxiv_paper.pdf_url
                        if not paper.abstract:
                            paper.abstract = arxiv_paper.abstract
                        if not paper.url:
                            paper.url = arxiv_paper.url

                cited_by = item.get("inline_links", {}).get("cited_by", {})
                paper.citations = cited_by.get("total", 0)
                papers.append(paper)
            except Exception as e:
                print(f"[Scholar] 解析结果失败: {e}")
                continue
        return papers
