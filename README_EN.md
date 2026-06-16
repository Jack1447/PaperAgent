# PaperAgent

Multi-Agent Paper Retrieval & Reading Workbench — search, filter, and read academic papers by simply entering a research topic.

> *Simplified implementation for reference only. Performance may be suboptimal.*

[中文文档](README.md)

demo: asset\demo.mp4

## Features

- **Intelligent Retrieval**: LLM decomposes research topics into sub-directions, concurrently searches arXiv + Google Scholar
- **Paper Ranking**: Multi-dimensional scoring (source weight, keyword match, citations, freshness), deduplication & merging
- **Deep Reading**: Auto-parse PDFs, generate structured summaries (background, method, innovations, results, etc.)
- **Paper Review**: LLM-based multi-dimensional review (topic, methodology, experiments, writing, etc.)
- **Q&A Interaction**: Free-form questions on individual papers with multi-turn conversation support
- **Streaming Results**: Real-time paper cards appear as results arrive, no need to wait for completion

## Tech Stack

| Category | Technology |
|----------|------------|
| Agent Orchestration | LangGraph |
| LLM Integration | LiteLLM |
| Literature Search | arXiv API, SerpAPI / 302.ai Google Scholar |
| PDF Parsing | PyMuPDF |
| Vector Search | ChromaDB |
| Structured Storage | SQLite |
| Web Framework | FastAPI + Jinja2 Templates |

## Quick Start

### Prerequisites

- Python 3.10+
- Access to an LLM API (OpenAI-compatible interface)

### Installation

```bash
git clone <repo-url>
cd PaperAgent
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env` and fill in your LLM API credentials (required):

```env
# Main model (Summarize / Reading / Review)
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1

# Fast model (Planner / Search / Reflection)
FAST_LLM_MODEL=gpt-4o-mini
FAST_LLM_API_KEY=sk-your-key
FAST_LLM_BASE_URL=https://api.openai.com/v1

# Google Scholar (optional — uses arXiv only if not configured)
SCHOLAR_API_KEY=sk-your-key
SCHOLAR_BASE_URL=https://api.302.ai/serpapi/search
```

Search parameters can be adjusted in `config/search.yaml`:

```yaml
arxiv:
  max_results_per_keyword: 8   # Max papers per keyword
  sort_by: "relevance"
scholar:
  max_results_per_keyword: 10
max_final_papers: 15           # Final number of papers to keep
```

### Launch

```bash
python app.py
```

Open `http://127.0.0.1:8000` in your browser.

## Workflow

1. Enter a research topic (e.g., "Retrieval-Augmented Generation for scientific literature review")
2. The system automatically decomposes the topic and retrieves papers — paper cards appear in real time
3. Select papers of interest, click "Generate Summary" for structured summaries
4. Click "Review" for LLM-based multi-dimensional evaluation
5. Ask free-form questions in the paper dialog for deep reading

## Project Structure

```
PaperAgent/
├── app.py                 # Entry point
├── config/
│   ├── .env               # Environment variables (API Keys, etc.)
│   ├── settings.py        # Configuration loader
│   ├── llm.yaml           # LLM parameters
│   ├── search.yaml        # Search parameters
│   └── prompts.yaml       # Agent prompt templates
├── src/
│   ├── agents/            # Agent implementations
│   │   ├── planner.py     # Research topic decomposition
│   │   ├── search.py      # Paper retrieval orchestration
│   │   ├── summarize.py   # Paper summarization
│   │   ├── reading.py     # Paper Q&A
│   │   ├── review.py      # Paper review
│   │   └── reflection.py  # Retrieval quality reflection
│   ├── retrieval/         # Retrieval core
│   │   └── literature_retrieval.py  # Multi-source retrieval, dedup, scoring
│   ├── tools/
│   │   ├── arxiv_client.py   # arXiv API client
│   │   ├── scholar.py        # Google Scholar client
│   │   └── pdf_parser.py     # PDF parser
│   ├── workflows/
│   │   └── research.py    # ResearchWorkflow facade
│   ├── memory/            # SQLite / ChromaDB storage
│   ├── corpus/            # Paper corpus management
│   ├── llm/               # LLM invocation wrapper
│   ├── domain/            # Domain models
│   └── graph/             # LangGraph workflow definitions
├── web/                   # FastAPI web interface
│   ├── main.py
│   ├── templates/
│   └── static/
├── data/                  # Runtime data (PDF cache, SQLite DB)
└── tests/                 # Unit tests
```

## Retrieval Pipeline

1. **Planner Agent** uses LLM to break the user's topic into 3-5 sub-directions, each with 2-3 English keywords
2. **LiteratureRetrieval** iterates arXiv API + Google Scholar (optional), searching by each keyword
3. Deduplicates by arXiv ID or normalized title, merges information for the same paper across sources
4. Composite scoring: source weight + keyword match + citations + freshness + metadata completeness
5. Returns Top N papers sorted by score (default: 15)

## License

MIT
