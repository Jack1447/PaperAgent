"""
智能文本分块工具
按论文章节结构分块，支持滑动窗口
"""
from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.tools.pdf_parser import PaperText

LOW_VALUE_SECTIONS = {"references", "bibliography", "appendix"}


class PaperChunker:
    """
    论文分块器

    三层策略:
    Layer 1: 元数据层 (title + abstract, ~500 tokens)
    Layer 2: 结构化章节 (每块 ≤ 4000 tokens, overlap 800)
    Layer 3: RAG 检索层 (全文本向量化存 ChromaDB)
    """

    def __init__(
        self,
        chunk_size: int = 4000,
        chunk_overlap: int = 800,
    ):
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
        )

    def chunk(self, paper_text: PaperText) -> dict:
        """
        对论文进行三层分块

        Returns:
            {
                "metadata": str,          # Layer 1: 标题 + 摘要
                "chunks": list[str],       # Layer 2: 按章节分块
                "chunks_with_source": list[dict],  # Layer 3: 带来源标注的 chunks
            }
        """
        # === Layer 1: 元数据层 ===
        metadata = self._build_metadata(paper_text)

        # === Layer 2: 章节分块 ===
        # 优先保留章节结构
        section_texts = []
        for section_name, content in paper_text.sections.items():
            if self._is_low_value_section(section_name):
                continue
            if content.strip():
                section_texts.append(
                    f"## {section_name}\n{content}"
                )

        if section_texts:
            # 先按章节分
            chunks = []
            chunk_sections = []
            for section_name, content in paper_text.sections.items():
                if self._is_low_value_section(section_name):
                    continue
                if not content.strip():
                    continue
                section_text = f"## {section_name}\n{content}"
                sub_chunks = self.splitter.split_text(section_text)
                chunks.extend(sub_chunks)
                chunk_sections.extend([section_name] * len(sub_chunks))
        else:
            # 无法识别章节，直接分块全文本
            chunks = self.splitter.split_text(paper_text.full_text)
            chunk_sections = ["full_text"] * len(chunks)

        # === Layer 3: 带来源标注 ===
        chunks_with_source = []
        for i, chunk in enumerate(chunks):
            chunks_with_source.append({
                "chunk_id": f"chunk_{i}",
                "section": chunk_sections[i] if i < len(chunk_sections) else "unknown",
                "text": chunk,
            })

        return {
            "metadata": metadata,
            "chunks": chunks,
            "chunks_with_source": chunks_with_source,
        }

    def chunk_for_summarize(self, paper_text: PaperText) -> dict:
        """
        为 Summarize Agent 准备的分块
        只取 introduction + conclusion 做整体总结
        """
        intro = self._find_section(paper_text, ["introduction"])
        conclusion = self._find_section(paper_text, ["conclusion", "discussion", "summary"])
        if not intro and paper_text.full_text:
            intro = paper_text.full_text[:2500]
        if not conclusion and paper_text.full_text:
            conclusion = paper_text.full_text[-2500:]

        stage1_text = (
            f"Title: {paper_text.title}\n\n"
            f"Abstract: {paper_text.abstract}\n\n"
            f"Introduction: {intro[:2500] if intro else '(not found)'}\n\n"
            f"Conclusion: {conclusion[:2500] if conclusion else '(not found)'}\n\n"
        )

        # method + experiment 用于 stage 2
        method = self._find_section(paper_text, ["method", "methodology", "approach", "proposed method"])
        experiment = self._find_section(paper_text, ["experiment", "evaluation", "results"])

        stage2_text = (
            f"{method[:3000] if method else ''}\n\n"
            f"{experiment[:3000] if experiment else ''}\n\n"
        )

        return {
            "stage1": stage1_text,
            "stage2": stage2_text,
        }

    def _build_metadata(self, paper_text: PaperText) -> str:
        return (
            f"Title: {paper_text.title}\n"
            f"Authors: {paper_text.authors}\n"
            f"Abstract: {paper_text.abstract[:500]}"
        )

    def _find_section(self, paper_text: PaperText, names: list[str]) -> str:
        for name in names:
            for key, content in paper_text.sections.items():
                if name in key.lower():
                    return content
        return ""

    def _is_low_value_section(self, section_name: str) -> bool:
        lowered = section_name.lower().strip()
        return any(name in lowered for name in LOW_VALUE_SECTIONS)
