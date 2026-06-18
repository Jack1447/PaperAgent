# PaperAgent

Multi-Agent Paper Retrieval & Reading Workbench — search, filter, and read academic papers by simply entering a research topic.

> *Simplified implementation for reference only. Performance may be suboptimal.*

[中文文档](README.md)

## Demo

![paperagent-ezgif](asset/paperagent_gif.gif)

## Features

- **Intelligent Retrieval**: LLM decomposes research topics into sub-directions, searches Google Scholar and reverse-looks up arXiv versions for full-text information
- **Paper Ranking**: Multi-dimensional scoring (keyword match, citations, freshness, arXiv completeness), deduplication & merging
- **Deep Reading**: Auto-download & parse PDFs, generate structured summaries (background, method, innovations, results, etc.)
- **Paper Review**: LLM-based multi-dimensional review (topic, methodology, experiments, writing, etc.)
- **Multi-Paper Comparison**: Select multiple summarized papers and generate a side-by-side comparison table and synthesis with one click (resizable compare panel, per-session comparison history)
- **Q&A Interaction**: Free-form questions on individual papers with citation-traceable answers based on full-text retrieval
- **Streaming Results**: Papers stream one by one in real time via SSE, cards appear sequentially

## Tech Stack

| Category | Technology |
|----------|------------|
| Agent Orchestration | LangGraph |
| LLM Integration | LiteLLM |
| Literature Search | Google Scholar (SerpAPI) + arXiv title reverse lookup |
| PDF Parsing | PyMuPDF |
| Vector Search | SimpleStore (TF-IDF) |
| Structured Storage | SQLite |
| Web Framework | FastAPI + Vanilla HTML/CSS/JS |

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

# Google Scholar (required — primary search source)
SCHOLAR_API_KEY=sk-your-key
SCHOLAR_BASE_URL=https://api.302.ai/serpapi/search
```

Search parameters can be adjusted in `config/search.yaml`:

```yaml
scholar:
  max_results_per_keyword: 10  # Max papers per keyword
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
6. Click "Compare" to open the compare panel and run a side-by-side comparison of multiple summarized papers
7. Support notes and translation

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
│   │   ├── compare.py     # Multi-paper comparison
│   │   └── reflection.py  # Retrieval quality reflection
│   ├── retrieval/         # Retrieval core
│   │   └── literature_retrieval.py  # Scholar search, arXiv reverse lookup, dedup, scoring
│   ├── tools/
│   │   ├── arxiv_client.py   # arXiv title reverse lookup
│   │   ├── scholar.py        # Google Scholar client
│   │   └── pdf_parser.py     # PDF parser
│   ├── workflows/
│   │   └── research.py    # ResearchWorkflow facade
│   ├── memory/            # SimpleStore (TF-IDF) / SQLite storage
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

