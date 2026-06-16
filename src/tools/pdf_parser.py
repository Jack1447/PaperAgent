"""
PDF 解析模块
使用 PyMuPDF (fitz) 提取论文文本
"""
import os
from dataclasses import dataclass, field
import re

import fitz  # PyMuPDF


@dataclass
class PaperText:
    """解析后的论文文本"""
    title: str = ""
    authors: str = ""
    abstract: str = ""
    sections: dict[str, str] = field(default_factory=dict)  # 章节名 → 内容
    full_text: str = ""
    page_count: int = 0


# 常见论文章节标题模式
SECTION_PATTERNS = [
    "abstract", "introduction", "related work", "background",
    "method", "methodology", "approach", "proposed method",
    "experiment", "evaluation", "results",
    "discussion", "analysis",
    "conclusion", "summary", "future work",
    "appendix", "references", "bibliography",
]

SECTION_ALIASES = {
    "abstract": "abstract",
    "introduction": "introduction",
    "related work": "related work",
    "background": "background",
    "method": "method",
    "methodology": "method",
    "approach": "method",
    "proposed method": "method",
    "experiment": "experiment",
    "experiments": "experiment",
    "evaluation": "experiment",
    "results": "results",
    "discussion": "discussion",
    "analysis": "analysis",
    "conclusion": "conclusion",
    "conclusions": "conclusion",
    "summary": "conclusion",
    "future work": "future work",
    "appendix": "appendix",
    "references": "references",
    "bibliography": "references",
}

STOP_SECTIONS = {"references", "bibliography"}
LOW_VALUE_SECTIONS = {"references", "bibliography", "appendix"}


def parse_pdf(pdf_path: str) -> PaperText:
    """解析 PDF 论文，提取文本和章节结构"""
    result = PaperText()

    if not os.path.exists(pdf_path):
        return result

    doc = fitz.open(pdf_path)
    result.page_count = len(doc)

    full_lines = []
    current_section = "preamble"
    sections: dict[str, list[str]] = {}

    for page in doc:
        blocks = page.get_text("blocks")
        blocks.sort(key=lambda b: (b[1], b[0]))  # 按 y, x 坐标排序（从上到下，从左到右）

        for block in blocks:
            text = _clean_line(block[4])
            if not text:
                continue

            # 跳过太短的行（可能是页码、页眉）
            if len(text) < 3:
                continue

            # 跳过明显的页眉/页脚
            if _is_noise_line(text):
                continue

            # 检测章节标题
            section_name = _detect_section(text)
            if section_name and len(text) < 200:
                current_section = section_name
                if current_section not in sections:
                    sections[current_section] = []
                if current_section in STOP_SECTIONS:
                    # References 后的内容通常污染问答和摘要，全文也不再追加。
                    continue
            else:
                if current_section not in sections:
                    sections[current_section] = []
                if current_section not in LOW_VALUE_SECTIONS:
                    sections[current_section].append(text)
                    full_lines.append(text)

    doc.close()

    # 组装结果
    result.full_text = "\n".join(full_lines)
    result.sections = {
        k: "\n".join(v) for k, v in sections.items()
    }

    # 提取标题（需要重新打开文档）
    with fitz.open(pdf_path) as title_doc:
        result.title = _extract_title(title_doc)

    # 提取摘要
    result.abstract = _find_section(sections, ["abstract"])

    return result


def parse_pdf_from_arxiv(arxiv_id: str, cache_dir: str = "") -> PaperText:
    """从 arXiv 下载并解析论文"""
    import requests

    if not cache_dir:
        # Use absolute path: project_root/data/pdf_cache
        _proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        cache_dir = os.path.join(_proj_root, "data", "pdf_cache")

    cache_path = os.path.join(cache_dir, f"{arxiv_id.replace('/', '_')}.pdf")

    if not os.path.exists(cache_path):
        # 下载 PDF
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            os.makedirs(cache_dir, exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(resp.content)
        except requests.RequestException as e:
            print(f"[PDF] 下载失败 {arxiv_id}: {e}")
            # 尝试 HTML 版本
            html_url = f"https://ar5iv.labs.arxiv.org/html/{arxiv_id}"
            try:
                resp = requests.get(html_url, timeout=30)
                if resp.status_code == 200:
                    # 简单提取 HTML 文本
                    return _parse_html(resp.text)
            except Exception:
                pass
            return PaperText()

    return parse_pdf(cache_path)


def _extract_title(doc) -> str:
    """从 PDF 提取标题（第一页大字体的文本块）"""
    page = doc[0]
    blocks = page.get_text("blocks")
    blocks.sort(key=lambda b: b[1])  # 按 y 坐标排序

    # 找前几个块中字体最大的
    candidates = []
    for block in blocks[:5]:
        text = block[4].strip()
        if 10 < len(text) < 300:
            candidates.append((block[3] - block[1], text))  # (字体大小, 文本)

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]
    return ""


def _detect_section(text: str) -> str | None:
    """检测文本是否为章节标题"""
    text_lower = _normalize_heading(text)

    # 跳过纯数字或太短的文本
    if len(text) < 3 or text.isdigit():
        return None

    heading = _strip_heading_number(text_lower)
    heading = heading.rstrip(":").strip()

    if heading in SECTION_ALIASES:
        return SECTION_ALIASES[heading]

    # 匹配 "Method: ..." 这类标题后带短说明的情况
    for pattern, canonical in SECTION_ALIASES.items():
        if heading.startswith(pattern + " ") and len(heading) <= len(pattern) + 40:
            return canonical

    # 纯大写短文本通常也是章节标题
    if text.isupper() and 5 < len(text) < 100:
        return text_lower

    return None


def _clean_line(text: str) -> str:
    """Normalize whitespace and common PDF artifacts in one text block."""

    text = text.replace("\x00", " ")
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_noise_line(text: str) -> bool:
    if text.isdigit():
        return True
    if re.fullmatch(r"\d+\s*/\s*\d+", text):
        return True
    if len(text) <= 2:
        return True
    return False


def _normalize_heading(text: str) -> str:
    text = text.lower().strip()
    text = text.replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
    return text


def _strip_heading_number(text: str) -> str:
    """Remove common numeric/roman heading prefixes."""

    text = re.sub(r"^\s*(section\s+)?\d+(\.\d+)*\.?\s+", "", text)
    text = re.sub(r"^\s*[ivxlcdm]+\.?\s+", "", text)
    return text.strip()


def _find_section(sections: dict, names: list[str]) -> str:
    """按名称列表查找章节内容"""
    for name in names:
        for key, content in sections.items():
            if name in key.lower():
                return content
    return ""


def _parse_html(html_text: str) -> PaperText:
    """简单的 HTML 文本提取（ar5iv 备用）"""
    import re
    result = PaperText()

    # 去除 HTML 标签
    clean = re.sub(r"<[^>]+>", " ", html_text)
    clean = re.sub(r"\s+", " ", clean)

    result.full_text = clean

    # 尝试提取标题
    title_match = re.search(r"<title>(.*?)</title>", html_text, re.IGNORECASE)
    if title_match:
        result.title = title_match.group(1).strip()

    return result
