"""Paper corpus module.

The corpus owns paper ingestion, chunking, metadata storage, summaries, and
retrieval. Agents call this module instead of coordinating ChromaDB, SQLite,
PDF parsing, and text splitting themselves.
"""
from __future__ import annotations

from typing import Any, Callable


class PaperCorpus:
    """Access to stored papers, summaries, and searchable chunks."""

    def __init__(
        self,
        chroma: Any | None = None,
        sqlite: Any | None = None,
        chunker: Any | None = None,
        pdf_loader: Callable[[str], Any] | None = None,
    ):
        self._chroma = chroma
        self._sqlite = sqlite
        self._chunker = chunker
        self._pdf_loader = pdf_loader

    @property
    def chroma(self) -> Any:
        if self._chroma is None:
            from src.memory.chroma_store import ChromaStore

            self._chroma = ChromaStore()
        return self._chroma

    @property
    def sqlite(self) -> Any:
        if self._sqlite is None:
            from src.memory.sqlite_store import SQLiteStore

            self._sqlite = SQLiteStore()
        return self._sqlite

    @property
    def chunker(self) -> Any:
        if self._chunker is None:
            from src.tools.text_splitter import PaperChunker

            self._chunker = PaperChunker()
        return self._chunker

    def load_arxiv_text(self, arxiv_id: str) -> Any:
        if self._pdf_loader is not None:
            return self._pdf_loader(arxiv_id)

        from src.tools.pdf_parser import parse_pdf_from_arxiv

        return parse_pdf_from_arxiv(arxiv_id)

    def prepare_summary_inputs(self, arxiv_id: str) -> tuple[Any, dict[str, str]]:
        """Load a paper and return summary-ready text sections."""

        paper_text = self.load_arxiv_text(arxiv_id)
        if not getattr(paper_text, "full_text", ""):
            return paper_text, {"stage1": "", "stage2": ""}
        return paper_text, self.chunker.chunk_for_summarize(paper_text)

    def store_paper_chunks(self, arxiv_id: str, paper_text: Any) -> None:
        """Chunk and store full paper text for later retrieval."""

        if not getattr(paper_text, "full_text", ""):
            return
        chunked = self.chunker.chunk(paper_text)
        self.chroma.add_chunks(arxiv_id, chunked["chunks_with_source"])

    def build_chunk_preview(
        self,
        paper_text: Any,
        limit: int = 8,
        chars_per_chunk: int = 3000,
    ) -> str:
        """Build a bounded text preview from parsed paper chunks."""

        if not getattr(paper_text, "full_text", ""):
            return ""
        chunked = self.chunker.chunk(paper_text)
        return "\n\n".join(
            chunk["text"][:chars_per_chunk]
            for chunk in chunked["chunks_with_source"][:limit]
        )

    def store_detail_chunks(self, arxiv_id: str, detail_text: str) -> None:
        if not detail_text.strip():
            return
        chunks = self.chunker.splitter.split_text(detail_text)
        chunks_with_source = [
            {"chunk_id": f"detail_{i}", "section": "technical_details", "text": chunk}
            for i, chunk in enumerate(chunks)
        ]
        self.chroma.add_chunks(f"{arxiv_id}_detail", chunks_with_source)

    def retrieve_chunks(
        self,
        arxiv_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        return self.chroma.search_chunks(arxiv_id, query, top_k=top_k)

    def get_summary(self, arxiv_id: str) -> str | None:
        return self.chroma.get_summary(arxiv_id)

    def save_summary(
        self,
        arxiv_id: str,
        title: str,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.chroma.add_summary(arxiv_id, title, summary, metadata or {})

    def save_paper_metadata(
        self,
        *,
        arxiv_id: str,
        title: str = "",
        authors: list[str] | None = None,
        abstract: str = "",
        url: str = "",
        published: str = "",
        citations: int = 0,
        summary: str = "",
    ) -> None:
        self.sqlite.save_paper(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors or [],
            abstract=abstract,
            url=url,
            published=published,
            citations=citations,
            summary=summary,
        )

    def get_paper_metadata(self, arxiv_id: str) -> dict[str, Any] | None:
        return self.sqlite.get_paper(arxiv_id)

    def paper_exists(self, arxiv_id: str) -> bool:
        return self.chroma.paper_exists(arxiv_id)
