"""FastAPI web server — custom frontend for PaperAgent."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Ensure .env is loaded
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncio
import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.domain.models import paper_uid
from src.workflows.research import ResearchWorkflow, parse_arxiv_link
from web.state import state

app = FastAPI(title="PaperAgent")

web_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=str(web_dir / "static")), name="static")

workflow: ResearchWorkflow | None = None


def get_workflow() -> ResearchWorkflow:
    global workflow
    if workflow is None:
        workflow = ResearchWorkflow()
    return workflow


def paper_to_dict(paper) -> dict:
    uid = paper_uid(paper)
    authors = getattr(paper, "authors", [])
    if isinstance(authors, str):
        authors_str = authors
    else:
        names = [str(x) for x in authors[:3]]
        if len(authors) > 3:
            names.append("et al.")
        authors_str = ", ".join(names)

    published = getattr(paper, "published", "")
    citations = int(getattr(paper, "citations", 0) or 0)
    sources = getattr(paper, "sources", [])
    score = getattr(paper, "retrieval_score", None)
    reasons = getattr(paper, "retrieval_reasons", [])
    abstract = getattr(paper, "abstract", "")

    # Check if PDF exists in cache
    has_pdf = False
    if uid and not uid.startswith("no-id:"):
        clean_id = uid.replace("/", "_")
        cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pdf_cache", f"{clean_id}.pdf")
        has_pdf = os.path.exists(cache_path)
    # Also check for no-id papers that user may have uploaded
    if not has_pdf and uid:
        clean_id = uid.replace("/", "_").replace("\\", "_")
        cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "pdf_cache", f"{clean_id}.pdf")
        has_pdf = os.path.exists(cache_path)

    return {
        "uid": uid,
        "title": getattr(paper, "title", "Untitled"),
        "abstract": abstract,
        "authors": authors_str,
        "year": published[:4] if published else "n.d.",
        "citations": citations,
        "sources": sources,
        "retrieval_score": round(score, 2) if score is not None else None,
        "retrieval_reasons": reasons[:4],
        "has_summary": uid in state.summaries,
        "summary": state.summaries.get(uid, ""),
        "has_review": uid in state.review_by_paper,
        "review": state.review_by_paper.get(uid, ""),
        "has_pdf": has_pdf,
    }


def build_state_summary() -> dict:
    return {
        "n_papers": len(state.papers),
        "papers": [paper_to_dict(p) for p in state.papers],
        "subtopics": state.subtopics,
        "chat_by_paper": state.chat_by_paper,
        "query": state.query,
    }


# ── Routes ──


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = web_dir / "templates" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/state")
async def get_state():
    return JSONResponse(build_state_summary())


@app.post("/api/search")
async def search(query: str = Form(...), max_results: int = Form(15)):
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="请输入研究主题")
    max_results = max(1, min(20, max_results))

    state.query = query
    state.papers = []
    state.subtopics = []
    state.selected_ids = set()
    state.summaries = {}
    state.chat_by_paper = {}
    state.review_by_paper = {}

    wf = get_workflow()
    plan_result = await wf.plan(query)
    if not plan_result.ok:
        msg = plan_result.failure.message if plan_result.failure else "规划失败"
        raise HTTPException(status_code=500, detail=msg)

    state.subtopics = plan_result.value

    search_result = await wf.search(query, max_papers=max_results)
    if not search_result.ok or not search_result.value:
        msg = search_result.failure.message if search_result.failure else "检索失败"
        raise HTTPException(status_code=500, detail=msg)

    state.papers = search_result.value.papers
    state.save()
    return JSONResponse(build_state_summary())


@app.post("/api/search-stream")
async def search_stream(query: str = Form(...), max_results: int = Form(15)):
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="请输入研究主题")
    max_results = max(1, min(20, max_results))

    state.query = query
    state.papers = []
    state.subtopics = []
    state.selected_ids = set()
    state.summaries = {}
    state.chat_by_paper = {}
    state.review_by_paper = {}

    async def event_stream():
        wf = get_workflow()

        # 1. Plan
        yield f"event: status\ndata: {json.dumps({'msg': '正在规划研究主题...'})}\n\n"
        plan_result = await wf.plan(query)
        if not plan_result.ok:
            yield f"event: error\ndata: {json.dumps({'msg': '规划失败'})}\n\n"
            return
        state.subtopics = plan_result.value
        yield f"event: subtopics\ndata: {json.dumps(plan_result.value)}\n\n"

        # 2. Stream search results one by one
        yield f"event: status\ndata: {json.dumps({'msg': '正在检索论文...'})}\n\n"
        papers = []
        async for paper in wf.search_stream(query, max_papers=max_results):
            papers.append(paper)
            state.papers = papers
            d = paper_to_dict(paper)
            yield f"event: paper\ndata: {json.dumps(d)}\n\n"

        yield f"event: done\ndata: {json.dumps({'n_papers': len(papers)})}\n\n"
        state.save()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/summarize-one")
async def summarize_one(paper_id: str = Form(...)):
    import asyncio
    from src.agents.summarize import SummarizeAgent

    paper = None
    for p in state.papers:
        if paper_uid(p) == paper_id:
            paper = p
            break
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")

    state.selected_ids.add(paper_id)

    agent = SummarizeAgent()
    result = await agent.run({"paper": paper})
    generated = result.get("summaries", {})
    if paper_id in generated:
        state.summaries[paper_id] = generated[paper_id]
    elif len(generated) == 1:
        state.summaries[paper_id] = next(iter(generated.values()))
    else:
        state.summaries.update(generated)

    state.save()

    # Check if PDF was saved during summarization by looking at disk
    _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    has_pdf = False
    clean = paper_id.replace("/", "_").replace("\\", "_")
    cache_path = os.path.join(_proj, "data", "pdf_cache", f"{clean}.pdf")
    has_pdf = os.path.exists(cache_path)
    if not has_pdf and hasattr(paper, "arxiv_id"):
        aid = getattr(paper, "arxiv_id", "") or paper_id
        clean2 = aid.replace("/", "_").replace("\\", "_")
        has_pdf = os.path.exists(os.path.join(_proj, "data", "pdf_cache", f"{clean2}.pdf"))

    return JSONResponse({
        "uid": paper_id,
        "summary": state.summaries.get(paper_id, ""),
        "has_pdf": has_pdf,
    })


@app.get("/api/pdf/{paper_id}")
async def serve_pdf(paper_id: str):
    _proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    clean = paper_id.replace("/", "_").replace("\\", "_").replace("no-id:", "")
    pdf_path = os.path.join(_proj, "data", "pdf_cache", f"{clean}.pdf")
    if os.path.exists(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf")
    raise HTTPException(status_code=404, detail="PDF 文件不存在")


@app.post("/api/translate")
async def translate_text(text: str = Form(...)):
    """Translate text using Qwen-MT-Turbo via 302.ai."""
    import requests

    api_key = os.getenv("TRANSLATE_API_KEY") or os.getenv("LLM_API_KEY") or ""
    endpoint = os.getenv("TRANSLATE_BASE_URL") or "https://api.302.ai/v1/chat/completions"

    if not api_key:
        raise HTTPException(status_code=503, detail="翻译 API Key 未配置")

    try:
        resp = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen-mt-turbo",
                "messages": [
                    {"role": "user", "content": text},
                ],
                "translation_options": {
                    "source_lang": "auto",
                    "target_lang": "Chinese",
                },
                "temperature": 0,
                "max_tokens": 4096,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        translated = data["choices"][0]["message"]["content"].strip()
        return JSONResponse({"translated": translated})
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"翻译服务不可用: {str(e)}")
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail="翻译服务返回格式异常")


@app.post("/api/upload-pdf")
async def upload_pdf(paper_id: str = Form(...), file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="请上传 PDF 文件")

    from src.tools.pdf_parser import parse_pdf
    from src.tools.text_splitter import PaperChunker
    from src.memory.chroma_store import SimpleStore

    _proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_dir = os.path.join(_proj_root, "data", "pdf_cache")
    os.makedirs(cache_dir, exist_ok=True)

    # Save uploaded PDF
    clean_id = paper_id.replace("/", "_").replace("\\", "_")
    pdf_path = os.path.join(cache_dir, f"{clean_id}.pdf")
    with open(pdf_path, "wb") as f:
        f.write(await file.read())

    # Parse
    try:
        paper_text = parse_pdf(pdf_path)
    except Exception as e:
        return JSONResponse({"error": f"PDF 解析失败: {str(e)}", "uid": paper_id}, status_code=400)

    if not paper_text.full_text:
        return JSONResponse({"error": "PDF 中未提取到文本内容", "uid": paper_id}, status_code=400)

    # Store chunks (use full chunk + summarize chunk)
    chunker = PaperChunker()
    store = SimpleStore()
    full_chunked = chunker.chunk(paper_text)
    store.add_chunks(clean_id, full_chunked["chunks_with_source"])

    # Build summary from full text
    summarize_chunked = chunker.chunk_for_summarize(paper_text)

    from config.settings import get_prompt_by_name
    from src.llm.provider import LLMProvider

    title = paper_text.title or ""
    authors = paper_text.authors or ""
    stage1_text = summarize_chunked["stage1"][:8000] if summarize_chunked.get("stage1") else paper_text.full_text[:8000]
    stage2_text = summarize_chunked.get("stage2", "")

    system = get_prompt_by_name("summarize.system")
    stage1_prompt = (
        get_prompt_by_name("summarize.stage1")
        .replace("{title}", title[:200])
        .replace("{authors}", authors[:200])
        .replace("{chunks}", stage1_text)
    )

    llm = LLMProvider(is_fast=False)
    summary = await llm.chat(
        messages=[{"role": "user", "content": stage1_prompt}],
        system=system,
    )

    if stage2_text and stage2_text.strip():
        stage2_prompt = (
            get_prompt_by_name("summarize.stage2")
            .replace("{retrieved_chunks}", stage2_text[:3000])
        )
        detail = await llm.chat(
            messages=[{"role": "user", "content": stage2_prompt}],
            system=system,
        )
        summary += "\n\n" + detail

    # Save all
    state.summaries[paper_id] = summary

    # Also save to corpus
    from src.corpus.paper_corpus import PaperCorpus
    corpus = PaperCorpus()
    corpus.chroma.add_chunks(clean_id, full_chunked["chunks_with_source"])
    corpus.save_summary(clean_id, title, summary, {"authors": authors})

    state.save()
    return JSONResponse({
        "uid": paper_id,
        "summary": summary,
        "title": title,
        "page_count": paper_text.page_count,
    })


@app.post("/api/review")
async def review_paper(paper_id: str = Form(...)):
    paper_title = ""
    paper_abstract = ""
    for p in state.papers:
        if paper_uid(p) == paper_id:
            paper_title = getattr(p, "title", "")
            paper_abstract = getattr(p, "abstract", "")
            break

    wf = get_workflow()
    result = await wf.review_paper(
        paper_id=paper_id,
        paper_title=paper_title,
        paper_abstract=paper_abstract,
        paper_summary=state.summaries.get(paper_id, ""),
    )
    review = result.value if result.ok else (
        result.failure.message if result.failure else "审稿失败"
    )
    state.review_by_paper[paper_id] = review
    state.save()
    return JSONResponse({"review": review, "uid": paper_id})


@app.post("/api/ask")
async def ask_paper(paper_id: str = Form(...), question: str = Form(...)):
    paper_title = ""
    paper_abstract = ""
    for p in state.papers:
        if paper_uid(p) == paper_id:
            paper_title = getattr(p, "title", "")
            paper_abstract = getattr(p, "abstract", "")
            break

    if paper_id not in state.chat_by_paper:
        state.chat_by_paper[paper_id] = []

    history = state.chat_by_paper[paper_id].copy()
    state.chat_by_paper[paper_id].append({"role": "user", "content": question})

    wf = get_workflow()
    result = await wf.ask_paper(
        paper_id=paper_id,
        paper_title=paper_title,
        paper_abstract=paper_abstract,
        paper_summary=state.summaries.get(paper_id, ""),
        question=question,
        chat_history=history,
    )
    answer = result.value if result.ok else (
        result.failure.message if result.failure else "回答失败"
    )
    state.chat_by_paper[paper_id].append({"role": "assistant", "content": answer})
    state.save()

    return JSONResponse({
        "answer": answer,
        "history": state.chat_by_paper[paper_id],
    })


@app.post("/api/add-paper")
async def add_paper(link: str = Form(...)):
    import asyncio
    from src.tools.arxiv_client import ArxivClient

    arxiv_id = parse_arxiv_link(link.strip())
    if not arxiv_id:
        raise HTTPException(status_code=400, detail="无法解析 arXiv ID")

    client = ArxivClient()
    paper = await asyncio.to_thread(client.get_paper_by_id, arxiv_id)
    if not paper:
        raise HTTPException(status_code=404, detail="未找到该论文")

    uid = paper_uid(paper)
    known_ids = {paper_uid(p) for p in state.papers}
    if uid not in known_ids:
        state.papers.insert(0, paper)
        state.manual_links.append(link.strip())
    state.save()
    return JSONResponse(build_state_summary())


@app.post("/api/reset")
async def reset():
    state.reset()
    state.save()
    return JSONResponse({"ok": True})


def main():
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
