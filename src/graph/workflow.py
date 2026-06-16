"""
LangGraph 工作流编排
完整 Agent 协作流程: Planner → Search → Summarize(并行) → Reading → Review

关键特性:
- 反思循环: Planner/Search 阶段不通过则自动重试 (最多 2-3 次)
- 并行分发: Summarize Agent 用 LangGraph Send() 并行处理多篇论文
- 人工干预: 搜索结果展示后可暂停等待用户操作
- 错误处理: 各节点 try-except，单个失败不影响整体
"""
import traceback

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Send

from src.agents.planner import PlannerAgent
from src.agents.search import SearchAgent
from src.agents.summarize import SummarizeAgent
from src.agents.reading import ReadingAgent
from src.agents.review import ReviewAgent
from src.agents.reflection import ReflectionAgent
from src.memory.sqlite_store import SQLiteStore
from src.graph.state import AgentState


def _node_error(node: str, exc: Exception, recoverable: bool = True) -> dict:
    return {
        "errors": [{
            "node": node,
            "message": str(exc),
            "recoverable": recoverable,
        }],
        "fatal_error": not recoverable,
    }


async def planner_node(state: AgentState) -> dict:
    print("[Workflow] Planner ...")
    try:
        p = PlannerAgent()
        r = await p.run(state)
        if not state.get("plan_quality_pass"):
            r["plan_quality_pass"] = False
        return r
    except Exception as e:
        traceback.print_exc()
        return _node_error("planner", e, recoverable=False)


async def search_node(state: AgentState) -> dict:
    print("[Workflow] Search ...")
    try:
        s = SearchAgent()
        r = await s.run(state)
        if not state.get("search_quality_pass"):
            r["search_quality_pass"] = False
        return r
    except Exception as e:
        traceback.print_exc()
        return _node_error("search", e, recoverable=False)


async def summarize_node(state: AgentState) -> dict:
    """单篇论文摘要（并行执行）"""
    paper = state.get("paper")
    if not paper:
        return {"summaries": {}}

    aid = getattr(paper, "arxiv_id", "")
    title = getattr(paper, "title", "")[:60]

    try:
        s = SummarizeAgent()
        return await s.run(state)
    except Exception as e:
        traceback.print_exc()
        return {
            "summaries": {aid: f"failed: {e}"},
            **_node_error("summarize", e, recoverable=True),
        }


async def merge_summaries_node(state: AgentState) -> dict:
    sums = state.get("summaries", {})
    papers = state.get("papers", [])
    n = max(len(sums), len(papers))
    print(f"[Workflow] 合并 {len(sums)} 篇摘要 ({n} 篇论文)")

    try:
        sqlite = SQLiteStore()
        sqlite.save_search(
            query=state.get("user_query", ""),
            subtopics=state.get("subtopics", []),
            paper_count=n,
        )
    except Exception as e:
        return {
            "summary_quality_pass": True,
            **_node_error("merge", e, recoverable=True),
        }
    return {"summary_quality_pass": True}


async def reading_node(state: AgentState) -> dict:
    try:
        r = ReadingAgent()
        return await r.run(state)
    except Exception as e:
        return {"answer": str(e), **_node_error("reading", e, recoverable=True)}


async def review_node(state: AgentState) -> dict:
    try:
        r = ReviewAgent()
        return await r.run(state)
    except Exception as e:
        return {"review": str(e), **_node_error("review", e, recoverable=True)}


def dispatch_summaries(state: AgentState) -> list[Send]:
    papers = state.get("papers", [])
    print(f"[Workflow] 分发 {len(papers)} 篇论文 → Summarize")
    return [
        Send("summarize", {"paper": p})
        for p in papers
        if getattr(p, "arxiv_id", "")
    ]


def build_workflow(incl_reflection: bool = True) -> StateGraph:
    builder = StateGraph(AgentState)

    builder.add_node("planner", planner_node)
    builder.add_node("search", search_node)
    builder.add_node("dispatch", lambda s: s)
    builder.add_node("summarize", summarize_node)
    builder.add_node("merge", merge_summaries_node)
    builder.add_node("reading", reading_node)
    builder.add_node("review", review_node)
    builder.add_node("done", lambda s: s)

    builder.set_entry_point("planner")

    if incl_reflection:
        builder.add_node("refl_plan", _refl_plan)
        builder.add_node("refl_search", _refl_search)
        builder.add_conditional_edges(
            "planner",
            _route_after_planner_with_reflection,
            {"refl_plan": "refl_plan", "error": END},
        )
        builder.add_conditional_edges(
            "refl_plan", _route_plan,
            {"search": "search", "planner": "planner", "error": END},
        )
    else:
        builder.add_conditional_edges(
            "planner",
            _route_after_planner_without_reflection,
            {"search": "search", "error": END},
        )

    if incl_reflection:
        builder.add_conditional_edges(
            "search",
            _route_after_search,
            {"refl_search": "refl_search", "error": END},
        )
        builder.add_conditional_edges(
            "refl_search", _route_search,
            {"dispatch": "dispatch", "search": "search", "skip": END, "error": END},
        )
    else:
        builder.add_conditional_edges(
            "search",
            _route_search_without_reflection,
            {"dispatch": "dispatch", "skip": END, "error": END},
        )

    builder.add_conditional_edges("dispatch", dispatch_summaries, path_map=["summarize"])
    builder.add_edge("summarize", "merge")
    builder.add_edge("merge", "done")
    builder.add_edge("done", END)
    builder.add_edge("reading", END)
    builder.add_edge("review", END)

    return builder


# ---- Reflection helpers ----

async def _refl_plan(state: AgentState) -> dict:
    if state.get("fatal_error"):
        return {}
    if state.get("plan_quality_pass"):
        return {}
    try:
        r = ReflectionAgent()
        result = await r._check_plan(state)
        retry = state.get("plan_retry_count", 0)
        if not result.get("plan_quality_pass"):
            retry += 1
        result["plan_retry_count"] = retry
        return result
    except Exception as e:
        return _node_error("refl_plan", e, recoverable=True)


async def _refl_search(state: AgentState) -> dict:
    if state.get("fatal_error"):
        return {}
    if state.get("search_quality_pass"):
        return {}
    try:
        r = ReflectionAgent()
        return await r._check_search(state)
    except Exception as e:
        return _node_error("refl_search", e, recoverable=True)


def _route_after_planner_with_reflection(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    return "refl_plan"


def _route_after_planner_without_reflection(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    return "search"


def _route_after_search(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    return "refl_search"


def _route_plan(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    if state.get("plan_quality_pass") or state.get("plan_retry_count", 0) >= 2:
        return "search"
    return "planner"


def _route_search(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    if state.get("search_quality_pass") or state.get("search_retry_count", 0) >= 3:
        return "dispatch" if state.get("papers") else "skip"
    return "search"


def _route_search_without_reflection(state: AgentState) -> str:
    if state.get("fatal_error"):
        return "error"
    return "dispatch" if state.get("papers") else "skip"


def compile_workflow(incl_reflection: bool = False):
    return build_workflow(incl_reflection).compile(checkpointer=MemorySaver())


def compile_workflow_with_interrupt():
    builder = build_workflow(incl_reflection=False)
    return builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=["done"],
    )
