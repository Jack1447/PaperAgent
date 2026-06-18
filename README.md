# PaperAgent

多智能体论文检索与阅读工作台 —— 输入研究主题，自动搜索、筛选、阅读论文。

**仅为简单实现，效果较差，仅供参考。**

[English](README_EN.md)

## Demo

![paperagent-ezgif](asset/paperagent_gif.gif)

## 功能

- **智能检索**：输入研究主题，LLM 自动拆解为子方向，通过 Google Scholar 检索论文并逐篇反向查找 arXiv 版本补全全文信息
- **论文筛选**：多维度评分（关键词匹配度、引用量、时效性、arXiv 完整性），去重合并且排序
- **深度阅读**：自动下载解析 PDF，生成结构化中文摘要（背景、方法、创新点、实验结果等）
- **论文评审**：LLM 对论文进行多维度评审（选题、方法、实验、写作等）
- **多论文对比**：选取多篇已生成摘要的论文，一键生成横向对比表格与综述（可拖拽宽度的对比面板，会话内保留对比历史）
- **问答交互**：对单篇论文自由提问，基于论文全文进行引用溯源式回答
- **流式展示**：检索结果逐篇实时流式推送，论文卡片依次出现

## 技术栈

| 类别 | 技术 |
|------|------|
| Agent 编排 | LangGraph |
| LLM 接入 | LiteLLM |
| 文献检索 | Google Scholar (SerpAPI) + arXiv 标题反向查找 |
| PDF 解析 | PyMuPDF |
| 向量检索 | SimpleStore (TF-IDF) |
| 结构化存储 | SQLite |
| Web 框架 | FastAPI + 原生 HTML/CSS/JS |

## 快速开始

### 环境要求

- Python 3.10+
- 可用的 LLM API（支持 OpenAI 兼容接口）

### 安装

```bash
git clone <repo-url>
cd PaperAgent
pip install -r requirements.txt
```

### 配置

```bash
cp .env.example .env
```

编辑 `.env`，填入 LLM API 配置（必填）：

```env
# 主模型（Summarize / Reading / Review）
LLM_MODEL=gpt-4o
LLM_API_KEY=sk-your-key
LLM_BASE_URL=https://api.openai.com/v1

# 快速模型（Planner / Search / Reflection）
FAST_LLM_MODEL=gpt-4o-mini
FAST_LLM_API_KEY=sk-your-key
FAST_LLM_BASE_URL=https://api.openai.com/v1

# Google Scholar（必填 —— 主搜索源）
SCHOLAR_API_KEY=sk-your-key
SCHOLAR_BASE_URL=https://api.302.ai/serpapi/search
```

搜索参数可在 `config/search.yaml` 中调整：

```yaml
scholar:
  max_results_per_keyword: 10  # 每个关键词最多返回篇数
max_final_papers: 15           # 最终保留论文数
```

### 启动

```bash
python app.py
```

浏览器打开 `http://127.0.0.1:8000` 即可使用。

## 使用流程

1. 输入研究主题（如 "Retrieval-Augmented Generation for scientific literature review"）
2. 系统自动拆分主题并检索论文，论文卡片实时出现
3. 勾选感兴趣的论文，点击「总结」获取结构化中文总结
4. 点击「评审」获取 LLM 对论文的多维度评价
5. 在论文对话框自由提问，进行深度阅读
6. 点击「对比分析」展开对比面板，选取多篇已生成摘要的论文进行横向对比
7. 支持笔记与翻译

## 项目结构

```
PaperAgent/
├── app.py                 # 入口
├── config/
│   ├── .env               # 环境变量（API Key 等）
│   ├── settings.py        # 配置加载器
│   ├── llm.yaml           # LLM 参数
│   ├── search.yaml        # 检索参数
│   └── prompts.yaml       # Agent Prompt 模板
├── src/
│   ├── agents/            # Agent 实现
│   │   ├── planner.py     # 研究主题拆分
│   │   ├── search.py      # 论文检索调度
│   │   ├── summarize.py   # 论文摘要生成
│   │   ├── reading.py     # 论文问答
│   │   ├── review.py      # 论文评审
│   │   ├── compare.py     # 多论文对比分析
│   │   └── reflection.py  # 检索质量反思
│   ├── retrieval/         # 检索核心
│   │   └── literature_retrieval.py  # Scholar 检索、arXiv 反向查找、去重、评分
│   ├── tools/
│   │   ├── arxiv_client.py   # arXiv 标题反向查找
│   │   ├── scholar.py        # Google Scholar 客户端
│   │   └── pdf_parser.py     # PDF 解析
│   ├── workflows/
│   │   └── research.py    # ResearchWorkflow 门面
│   ├── memory/            # SimpleStore (TF-IDF) / SQLite 存储
│   ├── corpus/            # 论文语料管理
│   ├── llm/               # LLM 调用封装
│   ├── domain/            # 领域模型
│   └── graph/             # LangGraph 工作流定义
├── web/                   # FastAPI Web 界面
│   ├── main.py
│   ├── templates/
│   └── static/
├── data/                  # 运行时数据（PDF 缓存、SQLite DB）
└── tests/                 # 单元测试
```

